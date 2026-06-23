# ==========================================================
# JARVIS — Piper TTS Test
# Tests: text → Piper → raw PCM → sounddevice playback
# ==========================================================

import subprocess
import sounddevice as sd
import numpy as np
import os
import sys

# Add project root to path so config is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.config import PIPER_EXE, PIPER_MODEL, PIPER_SAMPLE_RATE

def speak(text: str):
    """Stream Piper TTS output directly to speakers. No file I/O."""
    process = subprocess.Popen(
        [PIPER_EXE, "--model", PIPER_MODEL, "--output-raw"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Send text and close stdin to trigger generation
    process.stdin.write(text.encode("utf-8"))
    process.stdin.close()

    # Stream raw PCM (16-bit signed, mono) directly to speakers
    stream = sd.RawOutputStream(
        samplerate=PIPER_SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    stream.start()

    while True:
        chunk = process.stdout.read(2048)
        if not chunk:
            break
        if len(chunk) % 2 != 0:
            chunk = chunk[:-1]
        if chunk:
            stream.write(np.frombuffer(chunk, dtype=np.int16))

    stream.stop()
    stream.close()
    process.wait()

    print(f"[OK] Spoke: {text}")


# --- Test phrases ---
if __name__ == "__main__":
    speak("All systems online. Good evening, Parth.")
    speak("I am JARVIS. Your personal AI assistant.")
    speak("Piper text to speech is fully operational.")