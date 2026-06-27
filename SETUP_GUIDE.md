# JARVIS macOS — Setup Guide

> Complete setup guide for JARVIS on Apple Silicon (M1/M2/M3/M4/M5).
> Tested on: Apple Silicon M5 MacBook, ARM64, 16GB unified memory, macOS clean install.

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| **Chip** | Apple Silicon (M1+) | M3/M4/M5 |
| **macOS** | 13 (Ventura) | 14+ (Sonoma/Sequoia) |
| **RAM** | 8 GB unified | 16 GB unified |
| **Python** | 3.10 | 3.11 |
| **Disk** | 5 GB free | 10 GB free |

JARVIS requires an Apple Silicon Mac. Intel Macs are not supported (MPS/Metal acceleration is M-series only).

---

## 2. What's Different from Windows

| Feature | Windows | macOS |
|---|---|---|
| **GPU for Whisper** | CUDA (int8_float16) | CPU only — CTranslate2 has no MPS backend |
| **GPU for LLM (Ollama)** | CUDA | Metal — automatic, zero config |
| **GPU for Embeddings** | CPU | MPS — auto-detected in `vector_store.py` |
| **Volume Control** | `pycaw` (COM API) | `osascript` (AppleScript) |
| **Brightness Control** | `screen-brightness-control` | `brightness` CLI (Homebrew) — built-in display only, not external monitors |
| **Window Management** | `pygetwindow` (Win32 API) | `osascript` (AppleScript via System Events) |
| **App Launcher** | PowerShell `Start-Process` | `open -a` + `system_profiler` |
| **Bluetooth** | `winrt` + `pybluez2` (silent pairing) | `blueutil` + `bleak` — pairing of **new** devices requires accepting a macOS system dialog (security feature); existing paired devices connect/disconnect silently |
| **Clipboard** | `win32gui` SendKeys | `osascript` keystroke |
| **System Monitor** | CPU/RAM/GPU (via `pynvml`) | CPU/RAM only — no GPU stats without NVIDIA; existing `try/except` handles gracefully |
| **File Paths** | `D:\JARVIS\...` | Relative paths via `config.py` |
| **Recycle Bin** | PowerShell `Clear-RecycleBin` | AppleScript `Finder.empty trash` |
| **Setup Script** | `setup.bat` | `setup.sh` |
| **Run Script** | `run.bat` | `run.sh` |

### Why is Whisper on CPU?

Faster-Whisper uses CTranslate2, which only supports CUDA and CPU backends. Apple's MPS (Metal Performance Shaders) is not supported by CTranslate2. On Apple Silicon, CPU inference is still fast due to the high single-core performance of M-series chips — expect ~1.5x realtime for the `large-v3-turbo` model on an M5.

---

## 3. Installation

### Quick Start (Recommended)

```bash
git clone https://github.com/parthsytus/JARVIS.git
cd JARVIS
chmod +x setup.sh run.sh
./setup.sh
```

`setup.sh` runs 7 steps automatically:

1. **Homebrew** — Installs if not present
2. **System dependencies** — `python@3.11`, `portaudio`, `ffmpeg`, `blueutil`, `brightness`
3. **Ollama** — Installs via Homebrew if not present
4. **Virtual environment** — Creates `venv/` with Python 3.11
5. **PyTorch** — Installs with Apple Silicon MPS support (~600MB)
6. **Python dependencies** — Installs everything in `requirements_mac.txt`
7. **Directories** — Creates `tools/piper/`, `models/piper/`, `data/`, `logs/`, `core/tts_output/`, `memory/store/`

After setup completes, follow the manual download steps below.

### Manual Setup (Step by Step)

<details>
<summary>Click to expand full manual setup</summary>

#### Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"
```

#### Install System Dependencies

```bash
brew install python@3.11 portaudio ffmpeg blueutil brightness
```

#### Install Ollama

```bash
brew install ollama
```

#### Create Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

#### Install PyTorch

```bash
pip install torch torchaudio torchvision
```

#### Install Python Dependencies

```bash
pip install -r requirements_mac.txt
```

#### Create Directories

```bash
mkdir -p tools/piper models/piper data logs core/tts_output memory/store
```

</details>

---

## 4. Manual Downloads

### Ollama Model

```bash
ollama pull gemma4:12b
```

Or whichever model is set in `config/config.py` (default: `gemma4:12b`).

### Piper TTS Binary

1. Go to: **https://github.com/rhasspy/piper/releases**
2. Download: `piper_macos_aarch64.tar.gz` (ARM64 Mac build)
3. Extract the `piper` binary
4. Place it at:
   ```
   JARVIS/tools/piper/piper
   ```
5. Make it executable:
   ```bash
   chmod +x tools/piper/piper
   ```

### Piper Voice Model (English)

1. Go to: **https://github.com/rhasspy/piper/blob/master/VOICES.md**
2. Find and download the `en_US-ryan-high` model
3. Download **both** files:
   - `en_US-ryan-high.onnx`
   - `en_US-ryan-high.onnx.json`
4. Place both in:
   ```
   JARVIS/models/piper/en_US-ryan-high.onnx
   JARVIS/models/piper/en_US-ryan-high.onnx.json
   ```


### API Keys (.env file)

Copy your `.env` file from the Windows version, or create a new one in the project root:

```
SERPER_API_KEY=your_serper_api_key_here
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback
```

---

## 5. Mac Permissions Setup

macOS requires explicit user permission for hardware access. Without these, specific features will fail silently or throw errors.

### Microphone Access

**Path:** System Settings → Privacy & Security → Microphone

Enable your terminal app (Terminal.app, iTerm2, or whichever you use to run JARVIS).

**What breaks without it:** JARVIS cannot hear you. The `pyaudio` microphone stream will fail to open, and you'll see `"ERROR: Could not initialize microphone"`.

### Bluetooth Access

**Path:** System Settings → Privacy & Security → Bluetooth

Enable your terminal app.

**What breaks without it:** `blueutil` commands will fail with permission errors. Bluetooth scanning, connecting, and disconnecting will not work. You'll see `"blueutil error"` messages.

### Automation / Accessibility Access

**Path:** System Settings → Privacy & Security → Automation

Enable your terminal app to control **System Events** and **Finder**.

For full window management (minimize, maximize, close), also grant access under:

**Path:** System Settings → Privacy & Security → Accessibility

**What breaks without it:** Volume control via `osascript`, window management (minimize/maximize/close), clipboard operations (copy/paste/cut), and app launching via `open -a` may fail or produce no effect. You'll see `"Not authorized to send Apple events"` errors.

---

## 6. Running JARVIS

### Start

```bash
./run.sh
```

Or manually:

```bash
source venv/bin/activate
python core/jarvis_core.py
```

### What the Startup Sequence Looks Like

```
[JARVIS] Starting Ollama server...
[JARVIS] Loading Piper TTS models into memory...
[JARVIS] Piper TTS loaded successfully.
[Memory] Loading embedding model...
[Memory] Embedding model 'all-MiniLM-L6-v2' loaded on MPS.
[Memory] ChromaDB ready — 0 existing entries.
[Memory] ========== MEMORY SYSTEM INIT ==========
[Memory] Episodic store loaded — 0 episodes.
[Memory] Ready — 0 episodes, 0 facts, 0 vector entries, 0 past sessions.
[Memory] ==========================================
[JARVIS] Loading Silero VAD...
[JARVIS] VAD loaded.
[JARVIS] Faster-Whisper loaded on CPU (CTranslate2 does not support MPS).
[JARVIS] Opening microphone...
[JARVIS] Calibrating microphone... (please stay quiet for 2 seconds)
[JARVIS] Calibration complete. Threshold: 250 (ambient: 45/120)
[JARVIS] Ready. Listening for wake word...
```

### Stop

Press `Ctrl+C`. JARVIS will consolidate the current session into long-term memory before shutting down.

---

## 7. Troubleshooting

### "Permission denied" on microphone

**Symptom:** `ERROR: Could not initialize microphone` or `OSError: [Errno -9996]`

**Fix:** Go to **System Settings → Privacy & Security → Microphone** and enable your terminal app. Restart the terminal after granting permission.

---

### Ollama connection refused

**Symptom:** `ConnectionError: HTTPConnectionPool(host='localhost', port=11434)`

**Fix:** Start the Ollama server manually:

```bash
ollama serve
```

Leave it running in a separate terminal window. `run.sh` attempts to auto-start Ollama, but if it fails silently, this is the fallback.

---

### Piper not found

**Symptom:** `FileNotFoundError: [Errno 2] No such file or directory: '.../tools/piper/piper'`

**Fix:**
1. Verify the binary exists: `ls -la tools/piper/piper`
2. Make it executable: `chmod +x tools/piper/piper`
3. If the file is missing, download `piper_macos_aarch64.tar.gz` from https://github.com/rhasspy/piper/releases

---

### PyAudio install failed

**Symptom:** `ERROR: Failed building wheel for PyAudio`

**Fix:**

```bash
brew install portaudio
pip install PyAudio
```

The `portaudio` Homebrew package provides the C library that PyAudio's pip build process needs.

---

### Bluetooth permission denied

**Symptom:** `blueutil error` or Bluetooth commands produce no results

**Fix:** Go to **System Settings → Privacy & Security → Bluetooth** and enable your terminal app. Restart the terminal.

---

### `blueutil: command not found`

**Fix:**

```bash
brew install blueutil
```

---

### `brightness: command not found`

**Fix:**

```bash
brew install brightness
```

Note: The `brightness` CLI only controls the built-in display. External monitors require manufacturer-specific tools.

---

### Whisper is slow

**Context:** Faster-Whisper runs on CPU because CTranslate2 doesn't support MPS. On Apple Silicon M-series chips, CPU performance is still strong.

**Mitigations:**
- Use `base` or `small` model instead of `large-v3-turbo` in `config/config.py`
- The `WHISPER_MODEL` setting controls model size

---

## 8. Architecture Notes

JARVIS is designed as a **fully offline, local-first AI assistant**. The core design goal is that no data leaves your machine except when explicitly needed.

### What runs locally (no internet)

- **Speech-to-Text:** Faster-Whisper (CTranslate2) — runs entirely on CPU
- **Language Model:** Ollama + Gemma4:12b — runs on Metal GPU via Ollama
- **Text-to-Speech:** Piper TTS — runs locally via ONNX runtime
- **Memory System:** ChromaDB + sentence-transformers — all stored in `memory/store/`
- **System Control:** Volume, brightness, window management — all via local `osascript`

### What uses the internet (only when triggered)

- **Web Search:** DuckDuckGo / Serper API — only when the LLM decides a factual question needs live data
- **Spotify:** Spotipy API — only when music control is requested
- **Currency Exchange:** Open Exchange Rates API — only for currency conversion

### Groq Fallback

The system supports Groq as an optional cloud LLM fallback. If configured in `.env`, it can be used when Ollama is unavailable. This is a convenience feature — the system is fully functional without it. No data is sent to Groq unless explicitly configured and triggered.

---

## Project Structure

```
JARVIS/
├── config/
│   └── config.py                # All settings — paths, models, audio params
├── core/
│   ├── jarvis_core.py           # Main runtime loop (listen → think → speak)
│   ├── fast_lane.py             # System control (macOS native via osascript)
│   ├── test/                    # Test scripts
│   │   ├── fast_lane_test.py    # Fast lane tests (macOS version)
│   │   ├── test_piper.py        # Piper TTS test
│   │   ├── test_whisper.py      # Whisper STT test
│   │   └── test_wakeword.py     # Wake word detection test
│   └── test_memory_optimization.py
├── memory/                      # Persistent memory system (preserved from Windows)
│   ├── __init__.py
│   ├── vector_store.py          # ChromaDB + sentence-transformers (MPS)
│   ├── memory_manager.py        # Central orchestrator
│   ├── episodic_store.py        # Event/conversation memory (JSONL)
│   ├── semantic_store.py        # Facts about the user (JSON)
│   ├── procedural_store.py      # Learned interaction patterns (JSON)
│   ├── importance_scorer.py     # Memory importance + forgetting curve
│   ├── context_assembler.py     # Working memory builder
│   ├── consolidator.py          # STM → LTM pipeline
│   └── test_memory.py           # Memory system smoke test
├── tools/
│   ├── __init__.py
│   ├── web_tools.py             # Web search + weather + currency
│   ├── system_monitor.py        # CPU/RAM telemetry (psutil)
│   └── piper/                   # Piper TTS binary (gitignored)
├── models/                      # Model weights (gitignored)
│   └── piper/                   # Piper voice model files
├── bluetooth_handler.py         # macOS Bluetooth (blueutil + bleak)
├── setup.sh                     # One-command setup
├── run.sh                       # Quick launcher
├── requirements_mac.txt         # Python dependencies (version-pinned)
├── SETUP_GUIDE.md               # This file
├── .env                         # API keys (gitignored)
└── .gitignore
```
