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
OLLAMA_MODEL = "llama3.2"     # Change this one line to swap the brain
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

# ----------------------------------------------------------
# PIPER TTS SETTINGS
# ----------------------------------------------------------
PIPER_EXE = os.path.join(JARVIS_ROOT, "tools", "piper", "piper")
PIPER_MODELS_DIR = os.path.join(JARVIS_ROOT, "models", "piper")

# Active voice — change this one line to swap JARVIS's voice
PIPER_VOICE = "en_US-ryan-high"
PIPER_VOICE_HINDI = "hi_IN-rohan-medium"

# Full paths — auto-constructed from voice name, never hardcoded
PIPER_MODEL = os.path.join(PIPER_MODELS_DIR, f"{PIPER_VOICE}.onnx")
PIPER_CONFIG = os.path.join(PIPER_MODELS_DIR, f"{PIPER_VOICE}.onnx.json")

PIPER_MODEL_HINDI = os.path.join(PIPER_MODELS_DIR, f"{PIPER_VOICE_HINDI}.onnx")
PIPER_CONFIG_HINDI = os.path.join(PIPER_MODELS_DIR, f"{PIPER_VOICE_HINDI}.onnx.json")

# Audio output settings for Piper
PIPER_SAMPLE_RATE = 22050        # Ryan-high outputs at 22050Hz
PIPER_SAMPLE_RATE_HINDI = 22050  # Rohan outputs at 22050Hz
PIPER_OUTPUT_DIR = os.path.join(JARVIS_ROOT, "core", "tts_output")

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
    "jarvis", "hey jarvis", "hi jarvis", "hello jarvis", "jarvis yes", "yes jarvis",
    "जार्विस", "हे जार्विस", "हाय जार्विस", "हेलो जार्विस", "नमस्ते जार्विस",
    "जारविस", "हे जारविस", "हाय जारविस", "हेलो जारविस", "नमस्ते जारविस",
    "जारvis", "hey जारvis", "hi जारvis", "hello जारvis", "हे जारvis", "हाय जारvis", "हेलो जारvis"
]
