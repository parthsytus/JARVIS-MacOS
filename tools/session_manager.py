# ==========================================================
# JARVIS — Session Manager
# Connection pooling for external APIs using requests.Session
# ==========================================================

import requests
import threading
from typing import Optional

# Global session pool with thread-local storage
_thread_local = threading.local()

# Default adapter config for connection pooling
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 20
DEFAULT_MAX_RETRIES = 3


def _create_session() -> requests.Session:
    """Create a new session with connection pooling."""
    session = requests.Session()
    
    # Configure adapter for connection pooling
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=DEFAULT_POOL_CONNECTIONS,
        pool_maxsize=DEFAULT_POOL_MAXSIZE,
        max_retries=DEFAULT_MAX_RETRIES,
        pool_block=False,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def get_session() -> requests.Session:
    """Get thread-local session (creates if needed)."""
    if not hasattr(_thread_local, "session") or _thread_local.session is None:
        _thread_local.session = _create_session()
    return _thread_local.session


def close_sessions():
    """Close all sessions (call at shutdown)."""
    if hasattr(_thread_local, "session") and _thread_local.session is not None:
        _thread_local.session.close()
        _thread_local.session = None


# Pre-configured sessions for specific services
_serper_session: Optional[requests.Session] = None
_serper_lock = threading.Lock()

_weather_session: Optional[requests.Session] = None
_weather_lock = threading.Lock()

_currency_session: Optional[requests.Session] = None
_currency_lock = threading.Lock()

_general_session: Optional[requests.Session] = None
_general_lock = threading.Lock()


def get_serper_session() -> requests.Session:
    """Get or create Serper.dev session with auth header preset."""
    global _serper_session
    if _serper_session is None:
        with _serper_lock:
            if _serper_session is None:
                session = _create_session()
                # Serper headers will be added per-request (API key varies)
                _serper_session = session
    return _serper_session


def get_weather_session() -> requests.Session:
    """Get or create wttr.in session."""
    global _weather_session
    if _weather_session is None:
        with _weather_lock:
            if _weather_session is None:
                session = _create_session()
                session.headers.update({"User-Agent": "JARVIS/1.0"})
                _weather_session = session
    return _weather_session


def get_currency_session() -> requests.Session:
    """Get or create exchangerate-api session."""
    global _currency_session
    if _currency_session is None:
        with _currency_lock:
            if _currency_session is None:
                session = _create_session()
                session.headers.update({"User-Agent": "JARVIS/1.0"})
                _currency_session = session
    return _currency_session


def get_general_session() -> requests.Session:
    """Get or create general-purpose session for DuckDuckGo, Wikipedia, etc."""
    global _general_session
    if _general_session is None:
        with _general_lock:
            if _general_session is None:
                session = _create_session()
                session.headers.update({"User-Agent": "JARVIS/1.0"})
                _general_session = session
    return _general_session


def close_all_sessions():
    """Close all service sessions."""
    global _serper_session, _weather_session, _currency_session, _general_session
    for session in [_serper_session, _weather_session, _currency_session, _general_session]:
        if session is not None:
            session.close()
    _serper_session = _weather_session = _currency_session = _general_session = None
    close_sessions()