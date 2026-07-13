# ==========================================================
# JARVIS — Web Tools
# Internet search and real-time data fetching.
# Primary:  Serper.dev (Google results, 2500 free queries)
# Fallback: DuckDuckGo (no API key needed)
# ==========================================================

import requests
import warnings
from tools.session_manager import (
    get_serper_session, get_weather_session, get_currency_session, get_general_session,
    close_all_sessions
)

# Suppress noisy warnings from libraries
warnings.filterwarnings("ignore", category=DeprecationWarning)


# ==========================================================
# SERPER.DEV — Primary search engine (Google results)
# ==========================================================
def search_serper(query, api_key, max_results=2, recency_days=None):
    """Search the web using Serper.dev (Google Search API).

    Args:
        query: Search query string
        api_key: Serper.dev API key
        max_results: Number of results to return
        recency_days: If set, filter results to this many days (e.g., 365 for past year)

    Returns a summary string, or None if the API call fails.
    """
    if not api_key:
        return None

    try:
        session = get_serper_session()
        
        # Build payload with optional recency filter
        payload = {"q": query, "num": max_results}
        if recency_days:
            payload["recencyDays"] = recency_days
        
        resp = session.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        output = []

        # Knowledge Graph (instant answer — best quality)
        kg = data.get("knowledgeGraph", {})
        if kg:
            title = kg.get("title", "")
            desc = kg.get("description", "")
            if title and desc:
                output.append(f"[Knowledge Graph] {title}: {desc}")
            # Include attributes (e.g., "Population: 1.4 billion")
            for key, value in kg.get("attributes", {}).items():
                output.append(f"  {key}: {value}")

        # Answer Box (direct answer from Google)
        answer_box = data.get("answerBox", {})
        if answer_box:
            answer = answer_box.get("answer", "") or answer_box.get("snippet", "")
            title = answer_box.get("title", "")
            if answer:
                output.append(f"[Direct Answer] {title}: {answer}" if title else f"[Direct Answer] {answer}")

        # Organic search results
        for r in data.get("organic", [])[:max_results]:
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            if title and snippet:
                output.append(f"- {title}: {snippet}")

        if output:
            return "\n".join(output)

        return None

    except Exception as e:
        print(f"[Serper] Search failed: {e}")
        return None


# ==========================================================
# DUCKDUCKGO — Fallback search (no API key needed)
# ==========================================================
def _search_ddg(query, max_results=2):
    """Search the web using DuckDuckGo. Fallback when Serper is unavailable."""
    # Try the new 'ddgs' package first
    try:
        from ddgs import DDGS

        results = list(DDGS().text(query, max_results=max_results))

        if results:
            output = []
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                if title and body:
                    output.append(f"- {title}: {body}")
            if output:
                return "\n".join(output)

    except ImportError:
        pass
    except Exception:
        pass

    # Try legacy duckduckgo_search as fallback
    try:
        from duckduckgo_search import DDGS as LegacyDDGS

        results = list(LegacyDDGS().text(query, max_results=max_results))

        if results:
            output = []
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                if title and body:
                    output.append(f"- {title}: {body}")
            if output:
                return "\n".join(output)

    except Exception:
        pass

    return None


def _search_fallback(query):
    """Fallback search using DuckDuckGo Instant Answer API."""
    try:
        session = get_general_session()
        resp = session.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1},
            timeout=10,
        )
        data = resp.json()

        if data.get("Abstract"):
            return data["Abstract"]
        elif data.get("Answer"):
            return data["Answer"]
        elif data.get("RelatedTopics"):
            topics = []
            for t in data["RelatedTopics"][:3]:
                if isinstance(t, dict) and "Text" in t:
                    topics.append(f"- {t['Text']}")
            if topics:
                return "\n".join(topics)

        return None
    except Exception:
        return None


def _search_wikipedia(query):
    """Direct Wikipedia search as final fallback."""
    try:
        session = get_general_session()
        resp = session.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + query.replace(" ", "_"),
            timeout=5,
            headers={"User-Agent": "JARVIS/1.0"},
        )
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "")
            if extract:
                return extract
        return None
    except Exception:
        return None


# ==========================================================
# UNIFIED SEARCH — Serper first, then fallback chain
# ==========================================================
def search_web(query, api_key="", max_results=1, recency_days=None):
    """Search the web. Uses Serper.dev first, falls back to DuckDuckGo.

    Args:
        query: The search query.
        api_key: Serper.dev API key. If empty, skips Serper.
        max_results: Number of results to fetch.
        recency_days: If set, filter results to this many days (Serper only).
    """
    # 1. Try Serper.dev (best quality — Google results)
    if api_key:
        result = search_serper(query, api_key, max_results, recency_days)
        if result:
            return result
        print("[Serper] No results, falling back to DuckDuckGo...")

    # 2. Try DuckDuckGo
    result = _search_ddg(query, max_results)
    if result:
        return result

    # 3. Try DDG Instant Answer API
    result = _search_fallback(query)
    if result:
        return result

    # 4. Try Wikipedia
    result = _search_wikipedia(query)
    if result:
        return result

    return "Could not find relevant information online."


# ==========================================================
# WEATHER
# ==========================================================
def get_weather(city=None):
    """Get current weather from wttr.in. Auto-detects location if no city given."""
    try:
        session = get_weather_session()
        url = f"https://wttr.in/{city}?format=j1" if city else "https://wttr.in/?format=j1"
        resp = session.get(url, timeout=5)
        data = resp.json()

        current = data["current_condition"][0]
        location = data.get("nearest_area", [{}])[0]

        city_name = location.get("areaName", [{}])[0].get("value", "Unknown")
        region = location.get("region", [{}])[0].get("value", "")
        country = location.get("country", [{}])[0].get("value", "")
        temp_c = current["temp_C"]
        feels_like = current["FeelsLikeC"]
        desc = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind_kmph = current["windspeedKmph"]
        visibility = current.get("visibility", "N/A")

        location_str = city_name
        if region:
            location_str += f", {region}"
        if country:
            location_str += f", {country}"

        return (
            f"Weather in {location_str}: {temp_c} degrees celsius (feels like {feels_like} degrees celsius), "
            f"{desc}, Humidity {humidity}%, Wind {wind_kmph} km per hour, "
            f"Visibility {visibility} km"
        )
    except Exception as e:
        return f"Weather fetch failed: {e}"


# ==========================================================
# CURRENCY CONVERSION
# ==========================================================
_CURRENCY_KEYWORDS = [
    "rupee", "rupees", "dollar", "dollars", "euro", "euros",
    "pound", "pounds", "yen", "currency", "exchange rate",
    "convert", "in usd", "in inr", "in eur", "in gbp",
    "how much is", "equal to",
]

# Common currency name → ISO code mapping
_CURRENCY_CODES = {
    "rupee": "INR", "rupees": "INR", "indian rupee": "INR", "inr": "INR",
    "dollar": "USD", "dollars": "USD", "us dollar": "USD", "usd": "USD",
    "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP",
    "yen": "JPY", "jpy": "JPY",
    "yuan": "CNY", "cny": "CNY",
    "bitcoin": "BTC", "btc": "BTC",
}


def _detect_currencies(query):
    """Try to detect source and target currencies from a natural language query.

    Returns (from_code, to_code, amount) or None if detection fails.
    """
    import re
    lower = query.lower()

    # Try to find an amount (e.g., "100", "5000")
    amount_match = re.search(r'(\d+(?:\.\d+)?)', lower)
    amount = float(amount_match.group(1)) if amount_match else 1.0

    # Find all currency mentions in order
    found = []
    for name, code in _CURRENCY_CODES.items():
        pos = lower.find(name)
        if pos != -1:
            # Avoid duplicate codes
            if not found or found[-1][1] != code:
                found.append((pos, code))

    # Sort by position in the query
    found.sort(key=lambda x: x[0])

    if len(found) >= 2:
        # Check if it's asking for an item price that happens to mention two currencies
        if any(kw in lower for kw in ["price", "cost", "share", "stock", "buy"]):
            return None
        return found[0][1], found[1][1], amount
    elif len(found) == 1:
        # If only one currency found, make sure they aren't asking for the price of an item/stock
        if any(kw in lower for kw in ["price", "cost", "share", "stock", "buy", "how much is a"]):
            # Allow "price of [currency]" like "price of dollar"
            if not any(f"price of {name}" in lower for name in _CURRENCY_CODES.keys()):
                return None
                
        # Also require that it's either an explicit conversion or a relatively short query
        explicit = any(kw in lower for kw in ["convert", "exchange rate"])
        if not explicit and " in " not in lower and " to " not in lower and len(lower.split()) > 5:
            return None

        code = found[0][1]
        if code == "USD":
            return "USD", "INR", amount  # Default: USD → INR
        else:
            return code, "USD", amount  # Default: X → USD

    return None


def get_currency_rate(from_code, to_code, amount=1.0):
    """Get live currency conversion using the free exchangerate-api.

    Uses https://open.er-api.com (no API key needed, updates daily).
    """
    try:
        session = get_currency_session()
        resp = session.get(
            f"https://open.er-api.com/v6/latest/{from_code}",
            timeout=10,
        )
        data = resp.json()

        if data.get("result") != "success":
            return f"Currency API error: {data.get('error-type', 'unknown')}"

        rates = data.get("rates", {})
        if to_code not in rates:
            return f"Could not find exchange rate for {to_code}."

        rate = rates[to_code]
        converted = round(amount * rate, 2)

        return (
            f"Currency conversion: {amount} {from_code} = {converted} {to_code}. "
            f"Exchange rate: 1 {from_code} = {rate} {to_code}. "
            f"Data updated: {data.get('time_last_update_utc', 'unknown')}"
        )
    except Exception as e:
        return f"Currency conversion failed: {e}"


def _is_currency_query(query):
    """Check if the query is about currency conversion."""
    lower = query.lower()
    return any(kw in lower for kw in _CURRENCY_KEYWORDS)


# ==========================================================
# QUERY ROUTER — picks the best data source
# ==========================================================
_WEATHER_KEYWORDS = [
    "weather", "temperature outside", "rain", "raining",
    "sunny", "cloudy", "forecast", "hot outside", "cold outside",
    "humidity", "wind speed",
]

# ----------------------------------------------------------
# SEARCH CACHE — avoid redundant network calls
# ----------------------------------------------------------
import hashlib
from datetime import datetime as _dt, timedelta as _td

_search_cache = {}
_MAX_CACHE_SIZE = 50
_CACHE_TTL = _td(hours=1)
_WEATHER_CACHE_TTL = _td(minutes=30)


def _cache_put(key, result):
    """Store a result in the search cache, evicting old entries if full."""
    if len(_search_cache) >= _MAX_CACHE_SIZE:
        # Evict oldest half
        sorted_keys = sorted(_search_cache.keys(), key=lambda k: _search_cache[k][1])
        for k in sorted_keys[:_MAX_CACHE_SIZE // 2]:
            del _search_cache[k]
    _search_cache[key] = (result, _dt.now())


def perform_search(query, weather_city=None, serper_api_key="", recency_days=None):
    """Route a query to the best data source and return results.

    Priority: Cache → Weather API → Currency API → Serper.dev → DuckDuckGo → Wikipedia
    """
    lower = query.lower()

    # Check cache first
    cache_key = hashlib.md5(lower.strip().encode()).hexdigest()
    if cache_key in _search_cache:
        cached_result, cached_ts = _search_cache[cache_key]
        is_weather = any(kw in lower for kw in _WEATHER_KEYWORDS)
        ttl = _WEATHER_CACHE_TTL if is_weather else _CACHE_TTL
        if _dt.now() - cached_ts < ttl:
            print(f"[Search] Cache hit for: {query}")
            return cached_result

    # Weather detection
    if any(kw in lower for kw in _WEATHER_KEYWORDS):
        result = get_weather(weather_city or None)
        _cache_put(cache_key, result)
        return result

    # Currency conversion — use dedicated API for accuracy
    if _is_currency_query(query):
        detected = _detect_currencies(query)
        if detected:
            from_code, to_code, amount = detected
            result = get_currency_rate(from_code, to_code, amount)
            if "failed" not in result.lower() and "error" not in result.lower():
                _cache_put(cache_key, result)
                return result
        # Fall through to web search if detection/API fails

    # General web search (Serper → DuckDuckGo → Wikipedia)
    result = search_web(query, api_key=serper_api_key, max_results=3, recency_days=recency_days)
    _cache_put(cache_key, result)
    return result


# ----------------------------------------------------------
# Quick self-test
# ----------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("=== Weather Test ===")
    print(get_weather())
    print()
    print("=== Currency Test ===")
    print(get_currency_rate("USD", "INR", 1))
    print(get_currency_rate("INR", "USD", 100))
    print()
    print("=== Serper Test ===")
    # To test Serper, set your API key here or pass via env
    import os
    test_key = os.environ.get("SERPER_API_KEY", "")
    print(search_web("Prime Minister of India 2026", api_key=test_key))
    print()
    print("=== DuckDuckGo Fallback ===")
    print(_search_ddg("President of the United States 2025"))
    print()
    print("=== Wikipedia Fallback ===")
    print(_search_wikipedia("President of the United States"))
