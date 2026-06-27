# ============================================================
# JARVIS — Central Configuration File
# All paths, model names, and settings live here.
# Change one line here = change behaviour across entire system.
# ============================================================

import os
from dotenv import load_dotenv

# ------------------------------------------------------------
# PROJECT ROOT
# Automatically detects where JARVIS is installed.
# This makes the project portable — works on any machine.
# ------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
JARVIS_ROOT = os.path.dirname(ROOT_DIR)
load_dotenv(os.path.join(JARVIS_ROOT, ".env"))

# ------------------------------------------------------------
# FFMPEG PATH INJECTION
# On Mac, Homebrew installs ffmpeg to /opt/homebrew/bin
# ------------------------------------------------------------
FFMPEG_BIN = "/opt/homebrew/bin"
FFMPEG_EXE = "ffmpeg"
if FFMPEG_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = FFMPEG_BIN + os.pathsep + os.environ["PATH"]
os.environ["FFMPEG_BINARY"] = FFMPEG_EXE

# ------------------------------------------------------------
# WHISPER SETTINGS
# ------------------------------------------------------------
WHISPER_MODEL = "large-v3-turbo"      # Natively supported by faster-whisper, 800MB VRAM Hindi/Hinglish
WHISPER_LANGUAGE = None        # None = Auto-detect language
MODELS_DIR = os.path.join(JARVIS_ROOT, "models")  # Where model weights save

# ------------------------------------------------------------
# OLLAMA SETTINGS
# ------------------------------------------------------------
OLLAMA_MODEL = "gemma4:12b"     # Change this one line to swap the brain
OLLAMA_URL = "http://localhost:11434/api/chat"

# ------------------------------------------------------------
# AUDIO SETTINGS
# ------------------------------------------------------------
SAMPLE_RATE = 16000            # Whisper requires exactly 16kHz
CHANNELS = 1                   # Mono — Whisper doesn't use stereo
CHUNK_SIZE = 1024              # Audio buffer size in frames

# ------------------------------------------------------------
# JARVIS IDENTITY
# ------------------------------------------------------------
JARVIS_NAME = "Jarvis"
USER_NAME = "Parth"
SHOW_THINKING = True

# ----------------------------------------------------------
# KOKORO TTS SETTINGS
# ----------------------------------------------------------
KOKORO_VOICE = "bm_george"
KOKORO_SAMPLE_RATE = 24000
KOKORO_PLAYBACK_SAMPLE_RATE = 24000



# ----------------------------------------------------------
# WEATHER SETTINGS
# ----------------------------------------------------------
WEATHER_CITY = ""                # Empty = auto-detect via IP. Set to "Delhi", "Mumbai", etc.

# ----------------------------------------------------------
# SERPER.DEV SEARCH API
# Sign up free at https://serper.dev — 2,500 free searches.
# Paste your API key below.
# ----------------------------------------------------------
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# ----------------------------------------------------------
# MEMORY SYSTEM
# Persistent memory across sessions — RAG + episodic + semantic
# ----------------------------------------------------------
MEMORY_DIR = os.path.join(JARVIS_ROOT, "memory", "store")
MEMORY_EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # 22MB, runs on CPU, 384-dim vectors
MEMORY_TOP_K = 2                # How many memories to retrieve per query
MEMORY_CONTEXT_BUDGET = 1500    # Max tokens for memory block in LLM context
MEMORY_DECAY_TAU = 30           # Forgetting curve time constant (days)
MEMORY_MID_SESSION_INTERVAL = 20  # Consolidate every N turns during long sessions

# ----------------------------------------------------------
# WAKE WORDS
# ----------------------------------------------------------
WAKE_WORDS = [
    "jarvis", "hey jarvis", "hi jarvis", "hello jarvis", "jarvis yes", "yes jarvis"
]
