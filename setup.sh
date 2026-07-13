#!/bin/bash
set -e
cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  JARVIS — MacOS Setup (Apple Silicon M-Series)"
echo "============================================================"
echo ""

# ── Step 1: Homebrew ─────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "[1/7] Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
else
    echo "[1/7] Homebrew already installed. Skipping."
fi

# ── Step 2: System Dependencies ──────────────────────────────
echo "[2/7] Installing system dependencies..."
brew install python@3.11 portaudio ffmpeg blueutil brightness

# ── Step 3: Ollama ───────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo "[3/7] Installing Ollama..."
    brew install ollama
else
    echo "[3/7] Ollama already installed. Skipping."
fi

# ── Step 4: Virtual Environment ──────────────────────────────
if [ ! -d "venv" ]; then
    echo "[4/7] Creating virtual environment..."
    python3.11 -m venv venv
else
    echo "[4/7] Virtual environment already exists. Skipping."
fi

# ── Step 5: PyTorch (Apple Silicon MPS) ─────────────────────
echo "[5/7] Installing PyTorch with Apple Silicon MPS support..."
echo "      (This is ~600MB — may take a few minutes)"
venv/bin/pip install --upgrade pip
venv/bin/pip install torch torchaudio torchvision

# ── Step 6: Python Dependencies ──────────────────────────────
echo "[6/7] Installing Python dependencies..."
venv/bin/pip install -r requirements_mac.txt

# ── Step 7: Directories ──────────────────────────────────────
echo "[7/7] Creating required directories..."
mkdir -p tools/piper
mkdir -p models/piper
mkdir -p data
mkdir -p logs
mkdir -p core/tts_output
mkdir -p memory/store

# ── Verify ───────────────────────────────────────────────────
echo ""
echo "Verifying installation..."
venv/bin/python -c "
import torch
print(f'  PyTorch: {torch.__version__}')
print(f'  MPS available: {torch.backends.mps.is_available()}')
import faster_whisper
print(f'  faster-whisper: OK')
import chromadb
print(f'  ChromaDB: {chromadb.__version__}')
import sounddevice as sd
print(f'  sounddevice: OK')
"

echo ""
echo "============================================================"
echo "  SETUP COMPLETE — Manual Steps Required:"
echo "============================================================"
echo ""
echo "  1. PULL OLLAMA MODEL"
echo "     ollama pull gemma4:12b-nvfp4"
echo "     (or whichever model is set in config/config.py)"
echo ""
echo "  2. DOWNLOAD PIPER TTS BINARY (ARM64 Mac)"
echo "     URL: https://github.com/rhasspy/piper/releases"
echo "     File to download: piper_macos_aarch64.tar.gz"
echo "     Extract the 'piper' binary to:"
echo "       JARVIS_MacOS/tools/piper/piper"
echo "     Then make it executable:"
echo "       chmod +x tools/piper/piper"
echo ""
echo "  3. DOWNLOAD PIPER VOICE MODEL"
echo "     URL: https://github.com/rhasspy/piper/blob/master/VOICES.md"
echo "     Download BOTH of these files:"
echo "       en_US-ryan-high.onnx"
echo "       en_US-ryan-high.onnx.json"
echo "     Place both in: JARVIS_MacOS/models/piper/"
echo ""
echo "  4. COPY YOUR .env FILE"
echo "     Copy .env from JARVIS Windows to JARVIS_MacOS/"
echo "     Keys needed: SERPER_API_KEY, GROQ_API_KEY (if using fallback)"
echo ""
echo "  5. GRANT MAC PERMISSIONS"
echo "     System Settings → Privacy & Security:"
echo "       → Microphone: enable for your terminal app"
echo "       → Bluetooth: enable for your terminal app"
echo "       → Automation: enable if using app/window control"
echo ""
echo "  6. RUN JARVIS"
echo "     ./run.sh"
echo ""
echo "============================================================"
