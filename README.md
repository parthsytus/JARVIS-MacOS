# JARVIS-MacOS 🤖🍏

**A fully offline, voice-activated AI assistant built natively for Apple Silicon.**

JARVIS-MacOS is a complete reimagining of the original JARVIS project for M1/M2/M3/M4/M5 Macs. Zero cloud dependencies. Local LLM execution via Ollama. Local speech-to-text via MLX Whisper. Local text-to-speech via Kokoro-MLX. A persistent, multi-tier long-term memory system that actually remembers you.

---

## ✨ Why This Exists

> **Your data shouldn't leave your machine.**

By leveraging the unified memory architecture of Apple Silicon, JARVIS achieves low-latency, conversational AI entirely offline. It thinks, hears, speaks, and remembers locally — no API keys required for core functionality.

---

## 🌟 Core Capabilities

| Feature | Technology | Status |
|---------|------------|--------|
| **Wake Word** | `openwakeword` — "Hey Jarvis" | ✅ Passive listening |
| **Speech-to-Text** | MLX Whisper (`whisper-large-v3-turbo`) | ✅ CPU, ~1.5× realtime on M5 |
| **LLM (Fast)** | Ollama + Qwen 3.5 4B (resident) | ✅ Tool calling, intent classification |
| **LLM (Complex)** | Ollama + Gemma 4 12B (on-demand) | ✅ Deep research, complex reasoning |
| **Text-to-Speech** | Kokoro-MLX (`bm_george`, 24kHz) | ✅ Streaming, in-memory |
| **Echo Cancellation** | WebRTC AEC + 1200ms BT delay buffer | ✅ No virtual audio devices needed |
| **Long-Term Memory** | ChromaDB + sentence-transformers (MPS) | ✅ Episodic, Semantic, Procedural tiers |
| **System Control** | `osascript`, `blueutil`, `bleak` | ✅ Volume, brightness, windows, apps, Bluetooth, Spotify |

---

## 🧠 Dual-Model Architecture

```
                    ┌─────────────────────┐
                    │   User Speech       │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Intent Classifier  │  ← Qwen 3.5 4B (resident)
                    │  (zero keywords)    │
                    └──────────┬──────────┘
                               ▼
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌────────────┐  ┌──────────────┐  ┌────────────┐
       │  CONVERSE  │  │  TOOL_ACTION │  │ DEEP_RSRCH │
       │  (no tools)│  │ (filtered    │  │ (Gemma 12B)│
       └────────────┘  │  tools)      │  └────────────┘
                       └──────────────┘
```

- **Fast path**: Qwen 3.5 4B stays resident — handles tool calls, classification, decomposition
- **Complex path**: Gemma 4 12B loads on-demand — deep research, synthesis, heavy reasoning
- **Groq fallback**: Optional cloud brain with 3s timeout → auto-fallback to local

---

## 🔬 Deep Research Pipeline

```
Topic → Decompose (Qwen 4B) → Fan-out Search (parallel) → Synthesize (Gemma 12B) → Save Report
```

Deterministic 4-stage pipeline runs in background with live status tracking. Produces structured, screen-readable reports with tables, pros/cons tension, and inline citations.

---

## 💾 Memory That Actually Works

Not "last 10 turns" — a **multi-tier memory system** with forgetting curves:

| Tier | Storage | Purpose | Retrieval |
|------|---------|---------|-----------|
| **Episodic** | JSONL | Conversations, events, emotion, importance | Recency + importance + MMR diversity |
| **Semantic** | JSON | Identity, goals, relationships, preferences, knowledge triples | Always injected (stable context) |
| **Procedural** | JSON | Learned patterns, peak hours, style prefs | Session-aware hints |
| **Vector (RAG)** | ChromaDB | Semantic search over all memories | MMR + decay-weighted ranking |

- **Importance scoring** at creation (keyword patterns, emotion, length, self-reference)
- **Ebbinghaus forgetting curve** at retrieval (τ = 30 days, reinforcement extends)
- **Mid-session consolidation** every 20 turns — crash-safe
- **Full consolidation on shutdown** — nothing lost

---

## 🎛 Native macOS Control

| Domain | Method | Notes |
|--------|--------|-------|
| Volume | `osascript` | Mute, unmute, set, relative |
| Brightness | `DisplayServices` + `brightness` CLI | Built-in display only |
| Windows | `osascript` (System Events) | Minimize, maximize, tile L/R, transfer, fullscreen, hide |
| Apps | `open -a` + `mdfind` cache | Fuzzy launch, 5-min TTL |
| Bluetooth | `blueutil` + `bleak` + IOBluetooth | Silent connect for paired; system dialog only for new pairing |
| Spotify | `spotipy` + AppleScript fallback | Play, queue, shuffle, loop, device targeting |
| Files | `osascript` keystrokes | Open, list, create, delete, copy/paste, empty trash |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/parthsytus/JARVIS-MacOS.git
cd JARVIS-MacOS

# 2. One-command setup (Homebrew, Python 3.11, Ollama, PyTorch MPS, deps, dirs)
chmod +x setup.sh run.sh
./setup.sh

# 3. Manual downloads (external binaries)
ollama pull gemma4:12b-nvfp4
# → Download Piper binary → tools/piper/piper
# → Download en_US-ryan-high voice → models/piper/

# 4. Create .env with your keys
cp .env.example .env  # edit with SERPER_API_KEY, GROQ_API_KEY, etc.

# 5. Grant macOS permissions (Microphone, Bluetooth, Automation, Accessibility)

# 6. Run
./run.sh
```

**Requirements:** Apple Silicon Mac (M1+), macOS 13+, 8 GB RAM (16 GB recommended), 10 GB free disk.

---

## 📁 Project Structure

```
JARVIS-MacOS/
├── config/
│   └── config.py              # Single source of truth — all settings
├── core/
│   ├── jarvis_core.py         # Main runtime loop (listen → think → speak)
│   ├── fast_lane.py           # System control (macOS native)
│   ├── intent_classifier.py   # LLM-driven routing (zero keywords)
│   ├── deep_research.py       # 4-stage research pipeline
│   ├── groq_brain.py          # Optional cloud fallback
│   ├── lazy_loaders.py        # Heavy models load on first use (~1.4 GB saved)
│   └── stt.py                 # MLX Whisper wrapper
├── memory/
│   ├── memory_manager.py      # Central orchestrator
│   ├── vector_store.py        # ChromaDB + MPS embeddings
│   ├── episodic_store.py      # JSONL event store
│   ├── semantic_store.py      # Facts, identity, goals, triples
│   ├── procedural_store.py    # Learned patterns
│   ├── importance_scorer.py   # Salience + forgetting curve
│   ├── context_assembler.py   # Working memory builder
│   └── consolidator.py        # STM → LTM pipeline
├── integrations/
│   └── __init__.py            # Hologram overlay (transparent UI)
├── tools/
│   ├── web_tools.py           # Serper/DDG/Wikipedia search, weather, currency
│   └── system_monitor.py      # CPU/RAM via psutil
├── bluetooth_handler.py       # Classic + BLE management
├── setup.sh                   # Automated environment bootstrap
├── run.sh                     # Quick launcher (starts Ollama, runs core)
├── requirements_mac.txt       # Pinned Python dependencies
├── SETUP_GUIDE.md             # Complete installation guide
├── .env                       # Your API keys (gitignored)
└── .gitignore
```

---

## 🔐 Privacy & Security

- **Zero telemetry** — no analytics, no crash reporting, no usage stats
- **Local-first** — STT, LLM, TTS, memory, system control all run on-device
- **Internet only when explicitly triggered**:
  - Web search (Serper/DuckDuckGo) — only for factual queries
  - Spotify — only for playback control
  - Currency exchange — only for conversion requests
- **Groq fallback** is optional, 3s timeout, disabled by default
- **Your `.env` and `memory/store/` never leave your machine** (gitignored)

---

## 🛠 Tech Stack

```
Python 3.11          │  Ollama                 │  ChromaDB
MLX / MLX-Whisper    │  PyTorch (MPS)          │  sentence-transformers
Kokoro-MLX           │  Silero VAD (torch.hub) │  pywebrtc_audio (AEC)
openwakeword         │  bleak + blueutil       │  rapidfuzz
psutil               │  spotipy                │  groq (optional)
```

---

## 📖 Documentation

- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** — Complete installation, permissions, troubleshooting
- **[config/config.py](config/config.py)** — Every tunable parameter in one place
- **Inline docs** — Every module has a header explaining its contract

---

## 🤝 Contributing

1. Fork → branch → PR
2. Run `ruff check .` and `ruff format .` before committing
3. Keep `config.py` as the single source of truth
4. No hardcoded paths — use `JARVIS_ROOT` from config
5. Lazy-load heavy imports (see `core/lazy_loaders.py`)

---

## 📄 License

MIT — use it, modify it, build on it.

---

## 🙏 Acknowledgments

- **Ollama** for making local LLMs trivial on Mac
- **MLX / Apple** for Apple Silicon acceleration
- **rhasspy/piper** and **hexgrad/kokoro** for local TTS
- **snakers4/silero-vad** for best-in-class VAD
- **chromadb** for vector storage
- **serper.dev** for clean search API

---

**Built with ☕ on Apple Silicon. Runs everywhere M-series goes.**