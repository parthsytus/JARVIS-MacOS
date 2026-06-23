# ============================================================
# JARVIS — Whisper Speech-to-Text Test
# Tests the full pipeline: Microphone → PyAudio → Whisper → Text
# Run this to confirm Step 2 is working correctly.
# ============================================================

import sys
import os

# Load JARVIS config first — this injects ffmpeg into PATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'config'))
import config

# Patch Whisper's load_audio to use our local ffmpeg
# This overrides the hardcoded "ffmpeg" string at runtime
# Works on any machine regardless of where JARVIS is installed
import whisper.audio

_original_load_audio = whisper.audio.load_audio

def _patched_load_audio(file, sr=whisper.audio.SAMPLE_RATE):
    import subprocess
    cmd = [
        config.FFMPEG_EXE,
        "-nostdin",
        "-threads", "0",
        "-i", file,
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", str(sr),
        "-"
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e
    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0

whisper.audio.load_audio = _patched_load_audio

import whisper
import torch
import pyaudio
import wave
import tempfile

# ------------------------------------------------------------
# STEP 1 — Load Whisper model (GPU if available, else CPU)
# First run: downloads ~145MB model to D:\JARVIS\models\
# Every run after: loads instantly from local disk
# ------------------------------------------------------------
if torch.cuda.is_available():
    device = "cuda"
    print(f"GPU detected: {torch.cuda.get_device_name(0)}")
else:
    device = "cpu"
    print("GPU not available, shifting to CPU.")

print(f"Loading Whisper model '{config.WHISPER_MODEL}' on {device.upper()}...")
model = whisper.load_model(config.WHISPER_MODEL, device=device, download_root=config.MODELS_DIR)
print(f"Model '{config.WHISPER_MODEL}' loaded on {device.upper()}. Ready to listen.\n")

# ------------------------------------------------------------
# STEP 2 — Record audio from microphone
# ------------------------------------------------------------
RECORD_SECONDS = 5

print(f"Speak now. Recording for {RECORD_SECONDS} seconds...")
print(">>> ", end="", flush=True)

# Initialize PyAudio
audio = pyaudio.PyAudio()

# Open microphone stream
stream = audio.open(
    format=pyaudio.paInt16,        # 16-bit audio — standard quality
    channels=config.CHANNELS,      # Mono
    rate=config.SAMPLE_RATE,       # 16kHz — Whisper's requirement
    input=True,
    frames_per_buffer=config.CHUNK_SIZE
)

# Capture audio frames
frames = []
for _ in range(0, int(config.SAMPLE_RATE / config.CHUNK_SIZE * RECORD_SECONDS)):
    data = stream.read(config.CHUNK_SIZE)
    frames.append(data)

# Clean up the stream
stream.stop_stream()
stream.close()
audio.terminate()

print("Recording complete.\n")

# ------------------------------------------------------------
# STEP 3 — Save recording to a temp WAV file
# Whisper reads from a file, not raw bytes directly
# We use a temp file so nothing permanent is written to disk
# ------------------------------------------------------------
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
    tmp_path = tmp.name

with wave.open(tmp_path, 'wb') as wf:
    wf.setnchannels(config.CHANNELS)
    wf.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
    wf.setframerate(config.SAMPLE_RATE)
    wf.writeframes(b''.join(frames))

# ------------------------------------------------------------
# STEP 4 — Transcribe with Whisper (FP16 on GPU, FP32 on CPU)
# ------------------------------------------------------------
print("Transcribing...")
use_fp16 = next(model.parameters()).is_cuda
result = whisper.transcribe(model, tmp_path, language=config.WHISPER_LANGUAGE, fp16=use_fp16)

# Clean up temp file
os.unlink(tmp_path)

# ------------------------------------------------------------
# STEP 5 — Print result
# ------------------------------------------------------------
print("\n--- JARVIS HEARD ---")
print(result["text"].strip())
print("--------------------\n")