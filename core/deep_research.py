# ============================================================
# JARVIS — Deep Research Agent (Deterministic Pipeline)
# 
# Pipeline stages:
# 1. DECOMPOSE (Qwen 4B - resident): topic -> N sub-queries
# 2. FAN-OUT SEARCH (code): parallel web_search for each query
# 3. SYNTHESIZE (Gemma 12B - on-demand): all results -> report
# 4. SAVE + UNLOAD (code): write file, unload model
# ============================================================

import json
import os
import threading
import re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.fast_lane import resolve_save_path

# Current date for anchoring
CURRENT_DATE = datetime.now().strftime("%B %d, %Y")
CURRENT_YEAR = datetime.now().year

# Keywords that indicate a query needs date anchoring
RELATIVE_KEYWORDS = ["latest", "current", "newest", "now", "recent", "today", "this year"]

# ============================================================
# RESEARCH STATUS TRACKING (module-level, survives background thread)
# ============================================================
_research_status_lock = threading.Lock()
_research_status = {
    "active": False,
    "topic": None,
    "stage": None,           # "decompose" | "search" | "synthesize" | "save" | "done" | "error"
    "stage_progress": "",    # human-readable detail for current stage
    "sub_queries": None,
    "search_results": None,
    "report_path": None,
    "error": None,
    "started_at": None,
    "completed_at": None,
}

def _update_status(**kwargs):
    """Thread-safe status update."""
    with _research_status_lock:
        _research_status.update(kwargs)

def get_research_status():
    """Return a copy of current research status."""
    with _research_status_lock:
        return dict(_research_status)

def is_research_active():
    """Check if a research pipeline is currently running."""
    with _research_status_lock:
        return _research_status["active"]

# Stage 1: Decomposition prompt for Qwen 4B (resident, fast)
DECOMPOSE_PROMPT = """You are a query decomposer. Break the user's research topic into 4-6 DISTINCT, SPECIFIC search queries.

Today's date: {current_date}

Rules:
- Each query must cover a DIFFERENT aspect (no overlap)
- Queries must be specific enough to return useful results
- No generic queries like "latest iPhone" — use "iPhone 16 Pro Max specifications" etc.
- For time-sensitive topics, include the current year ({current_year}) in queries
- **For ANY query about "latest", "current", "newest", "recent" version of a product: ALSO generate a companion query checking if it's been superseded (e.g., "iPhone 17 successor to iPhone 16", "has MacBook Pro M4 been replaced by M5", "successor to iPhone 16"). This is a MANDATORY companion query for time-sensitive topics.**
- Output ONLY a JSON array of strings: ["query1", "query2", "query3", "query4", "query5", "query6"]

Examples:

Topic: "latest iPhone model"
Output: ["iPhone 16 Pro Max specifications features price {current_year}", "iPhone 16e India price release date features {current_year}", "iPhone 17 rumors expected features launch date {current_year}", "iPhone 16 vs 15 comparison which to buy {current_year}", "iPhone 16 Pro Max camera megapixels video capabilities {current_year}", "iPhone 16 battery life real world tests {current_year}", "iPhone 17 successor to iPhone 16 has iPhone 16 been superseded {current_year}"]

Topic: "best laptop for programming under 80000"
Output: ["MacBook Air M2 M3 programming performance {current_year}", "Dell XPS 13 Linux developer experience {current_year}", "Lenovo ThinkPad X1 Carbon keyboard Linux {current_year}", "ASUS ZenBook 14 OLED compile times {current_year}", "Framework Laptop 13 repairability Linux {current_year}", "HP Spectre x360 thermal throttling coding {current_year}"]

Topic: {topic}
Output:"""

# Stage 3: Synthesis prompt for Gemma 12B (on-demand, heavy)
SYNTHESIZE_PROMPT = """You are JARVIS's Deep Research Agent. Synthesize the search results into a compelling, screen-readable report.

Today's date: {current_date}

STYLE CONTRACT — follow these exactly:

FORMAT FOR HUMAN READING ON SCREEN, NOT A FORMAL REPORT:
- Start with a **QUICK TAKE** (2-3 punchy lines) — the hook that earns the read
- Then EXECUTIVE SUMMARY (2-3 sentences)
- Then KEY FINDINGS (bullets with **bold key facts**: numbers, names, verdicts — not whole sentences)
- Then PROS/CONS as tension ("but here's the catch"), not neutral lists
- Then DETAILED ANALYSIS (vary section transitions, don't repeat header patterns)
- Then RECOMMENDATIONS (actionable, specific)

VISUAL RULES:
- **Bold the key fact in every bullet** (the number, name, or verdict) — never bold whole sentences
- **One emoji per major section header max** (📱 hardware, 💰 pricing, ⚡ performance, 📸 camera, 🔮 future) — skip if nothing fits, never inline in sentences, never more than one per line
- **Short punchy sentences** over compound ones
- **PROS/CONS as tension**: "X excels at ___ but here's the catch: ___" not neutral lists
- **USE MARKDOWN TABLES** whenever comparing 2+ things across same attributes (models, prices, specs, versions) — if you catch yourself writing "X has ___ while Y has ___," that's a table, not a sentence. Hard requirement: 2+ things, same attributes.
- Vary section transitions — don't repeat the same header pattern

CONFLICT RESOLUTION:
- If search results conflict on what is "current" or "latest," prioritize the source with the most recent explicit date over the source that sounds most authoritative
- **CRITICAL for "latest/current/newest" claims:** If a result says "X is the latest" but its publication date is >6 months old, treat it as stale. Prefer sources with explicit recent dates (e.g., "released Sept 2025", "announced July 2026") over generic "latest" claims from older pages.
- If sources conflict and no clear recent date exists, state explicitly: "Sources conflict on the current model; as of {current_date}, the most recent confirmed release is X, but newer models may exist."
- If you're not confident which is actually current, say so explicitly rather than picking one silently

CITATION: Cite sources inline like (Query 1), (Query 3) — keep it minimal.

Research Topic: {topic}

Search Results:
{results}

Now write the report following the style contract above."""

def anchor_query(query, current_year):
    """Add current year to queries that need date anchoring."""
    query_lower = query.lower()
    # Check if query already has a version, model name, year, or date
    has_anchor = bool(re.search(r'\b(?:v?\d+\.\d+|v?\d+|iPhone\s+\d+|Galaxy\s+S\d+|Pixel\s+\d+|20\d{2}|19\d{2})\b', query))
    # Check if query uses relative time keywords
    needs_anchor = any(kw in query_lower for kw in RELATIVE_KEYWORDS)
    
    if needs_anchor and not has_anchor:
        return f"{query} {current_year}"
    return query

def build_decompose_messages(topic):
    """Build messages for decomposition stage (Qwen 4B)."""
    return [
        {"role": "system", "content": DECOMPOSE_PROMPT.format(topic=topic, current_date=CURRENT_DATE, current_year=CURRENT_YEAR)},
        {"role": "user", "content": topic}
    ]

def build_synthesize_messages(topic, search_results):
    """Build messages for synthesis stage (Gemma 12B)."""
    # Format search results
    results_text = ""
    for i, (query, result) in enumerate(search_results, 1):
        results_text += f"\n--- Query {i}: {query} ---\n{result}\n"
    
    return [
        {"role": "system", "content": SYNTHESIZE_PROMPT.format(topic=topic, results=results_text, current_date=CURRENT_DATE)},
        {"role": "user", "content": f"Synthesize the research on: {topic}"}
    ]


# ============================================================
# PIPELINE EXECUTION
# ============================================================

def run_deep_research_pipeline(query, save_path=None, context="", history=None, progress_callback=None):
    """
    Execute the deterministic 4-stage pipeline.
    Returns (success, result_dict).
    """
    from core.lazy_loaders import call_complex_model, call_fast_model, load_complex_model, unload_complex_model
    from core.jarvis_core import JARVIS_TOOLS, execute_tool_call
    from config.config import FAST_MODEL, FAST_NUM_CTX, FAST_NUM_PREDICT, FAST_KEEP_ALIVE
    
    # Initialize status tracking
    _update_status(
        active=True,
        topic=query,
        stage="decompose",
        stage_progress="Starting decomposition...",
        sub_queries=None,
        search_results=None,
        report_path=None,
        error=None,
        started_at=datetime.now().isoformat(),
        completed_at=None,
    )
    
    if progress_callback:
        progress_callback("Starting deep research pipeline...")
    
    # Resolve save path
    from core.fast_lane import resolve_save_path
    if save_path:
        target_path = resolve_save_path(save_path)
    else:
        desktop = str(Path.home() / "Desktop")
        target_path = os.path.join(desktop, f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    
    try:
# ============================================================
# STAGE 1: DECOMPOSE (Qwen 4B - resident, fast)
# ============================================================
        _update_status(stage="decompose", stage_progress="Decomposing topic into sub-queries...")
        
        if progress_callback:
            progress_callback("Stage 1/4: Decomposing topic into sub-queries...")
        
        decompose_messages = build_decompose_messages(query)
        response, error = call_fast_model(
            decompose_messages, 
            tools=None,  # No tools needed
            stream=False
        )
        
        if error:
            _update_status(stage="error", error=error, active=False, completed_at=datetime.now().isoformat())
            if progress_callback:
                progress_callback(f"Decomposition failed: {error}")
            return False, error
        
        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        
        # Parse JSON array of queries
        try:
            if content.startswith("```"):
                lines = content.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            
            sub_queries = json.loads(content)
            if not isinstance(sub_queries, list):
                raise ValueError("Not a list")
            sub_queries = [q for q in sub_queries if isinstance(q, str) and q.strip()]
            
        except (json.JSONDecodeError, ValueError) as e:
            if progress_callback:
                progress_callback(f"Failed to parse sub-queries: {e}. Using fallback.")
            # Fallback: generate basic queries
            sub_queries = [
                f"{query} overview",
                f"{query} specifications features",
                f"{query} price comparison",
                f"{query} reviews pros cons",
                f"{query} alternatives competitors",
                f"{query} latest updates 2024 2025"
            ]
        
        _update_status(sub_queries=sub_queries, stage_progress=f"Generated {len(sub_queries)} sub-queries")
        
        if progress_callback:
            progress_callback(f"Stage 1 complete: {len(sub_queries)} sub-queries generated")
        
        # Anchor queries with current year for time-sensitive queries
        sub_queries = [anchor_query(q, CURRENT_YEAR) for q in sub_queries]
        
        if progress_callback:
            progress_callback(f"Stage 1 complete: {len(sub_queries)} sub-queries generated (anchored)")
        
        # ============================================================
        # STAGE 2: FAN-OUT SEARCH (deterministic code)
        # ============================================================
        if progress_callback:
            progress_callback(f"Stage 2/4: Searching {len(sub_queries)} queries in parallel...")
        
        search_results = []
        
        def search_single(query_text):
            """Execute a single web_search and return (query, result)."""
            try:
                # Detect if query is time-sensitive and add recency filter
                query_lower = query_text.lower()
                recency_days = 365 if any(kw in query_lower for kw in RELATIVE_KEYWORDS) else None
                
                args = {"query": query_text}
                if recency_days:
                    args["recency_days"] = recency_days
                
                result, needs_followup = execute_tool_call("web_search", args)
                return (query_text, result)
            except Exception as e:
                return (query_text, f"Search failed: {e}")
        
        _update_status(stage="search", stage_progress=f"Searching {len(sub_queries)} queries in parallel...")
        
        # Execute searches in parallel (max 3 concurrent to avoid rate limits)
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_query = {executor.submit(search_single, q): q for q in sub_queries}
            for future in as_completed(future_to_query):
                query_text = future_to_query[future]
                try:
                    query_text, result = future.result(timeout=15)
                except Exception as e:
                    result = f"Search failed or timed out: {e}"
                search_results.append((query_text, result))
                if progress_callback:
                    progress_callback(f"  Completed: {query_text[:50]}...")
        
        _update_status(search_results=search_results, stage_progress=f"Completed {len(search_results)} searches")
        
        if progress_callback:
            progress_callback(f"Stage 2 complete: {len(search_results)} searches done")
        
        # ============================================================
        # STAGE 3: SYNTHESIZE (Gemma 12B - on-demand)
        # ============================================================
        _update_status(stage="synthesize", stage_progress="Loading Gemma 12B for synthesis...")
        
        if progress_callback:
            progress_callback("Stage 3/4: Loading Gemma 12B for synthesis...")
        
        # Load complex model
        from core.lazy_loaders import load_complex_model, unload_complex_model
        if not load_complex_model():
            if progress_callback:
                progress_callback("Failed to load complex model")
            return False, "Failed to load complex model"
        
        try:
            _update_status(stage="synthesize", stage_progress="Synthesizing report with Gemma 12B...")
            
            if progress_callback:
                progress_callback("Stage 3/4: Synthesizing report with Gemma 12B...")
            
            synthesize_messages = build_synthesize_messages(query, search_results)
            response, error = call_complex_model(
                synthesize_messages,
                tools=None,  # No tools needed for synthesis
                stream=True,
                think=False,  # No thinking needed for formatted report synthesis
            )
            
            if error:
                _update_status(stage="error", error=error, active=False, completed_at=datetime.now().isoformat())
                if progress_callback:
                    progress_callback(f"Synthesis failed: {error}")
                return False, error
            
            # Stream response: collect chunks as they arrive
            report_content = ""
            for line in response.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done"):
                    final_msg = data.get("message", {})
                    if final_msg.get("content"):
                        report_content = final_msg["content"]
                    break
                msg = data.get("message", {})
                if msg.get("content"):
                    report_content += msg["content"]
            
            report_content = report_content.strip()
            
        finally:
            # Always unload complex model after synthesis
            unload_complex_model()
        
        _update_status(stage="synthesize", stage_progress="Report synthesized")
        
        if progress_callback:
            progress_callback("Stage 3 complete: Report synthesized")
        
        # ============================================================
        # STAGE 4: SAVE + UNLOAD (deterministic)
        # ============================================================
        _update_status(stage="save", stage_progress="Saving report to file...")
        
        if progress_callback:
            progress_callback("Stage 4/4: Saving report to file...")
        
        try:
            with open(target_path, 'w') as f:
                f.write(report_content if report_content else "Research completed but no content generated.")
            
            _update_status(report_path=target_path, stage="done", active=False, completed_at=datetime.now().isoformat(), stage_progress="Research complete")
            
            if progress_callback:
                progress_callback(f"Research saved to {target_path}")
            
            return True, {
                "result": report_content,
                "file_path": target_path,
                "sub_queries": sub_queries,
                "search_count": len(search_results)
            }
            
        except Exception as e:
            _update_status(stage="error", error=str(e), active=False, completed_at=datetime.now().isoformat())
            if progress_callback:
                progress_callback(f"Failed to save file: {e}")
            return False, f"Failed to save file: {e}"
            
    except Exception as e:
        _update_status(stage="error", error=str(e), active=False, completed_at=datetime.now().isoformat())
        if progress_callback:
            progress_callback(f"Pipeline error: {e}")
        return False, str(e)


def start_background_research(query, save_path=None, context="", history=None, on_complete=None):
    """
    Start deep research pipeline in background thread.
    Returns immediately, calls on_complete(success, result) when done.
    """
    def research_thread():
        def progress(msg):
            print(f"[Deep Research Pipeline] {msg}")
        
        success, result = run_deep_research_pipeline(query, save_path, context, history, progress)
        if on_complete:
            on_complete(success, result)
    
    thread = threading.Thread(target=research_thread, daemon=True)
    thread.start()
    return thread


# ============================================================
# BACKWARD COMPATIBILITY
# ============================================================

def run_deep_research(query, save_path=None, context="", history=None, progress_callback=None):
    """Backward compatible entry point."""
    return run_deep_research_pipeline(query, save_path, context, history, progress_callback)