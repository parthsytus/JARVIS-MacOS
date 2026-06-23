import os
import sys
import time
from collections import deque
import numpy as np
import pyaudio
from openwakeword.model import Model
from faster_whisper import WhisperModel

# Ensure we can import from config
JARVIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, JARVIS_ROOT)

from config.config import SAMPLE_RATE, CHANNELS, CHUNK_SIZE

# Constants
SILENCE_DURATION = 0.8
MIN_RECORD_SECONDS = 0.5
MAX_RECORD_SECONDS = 30
PREROLL_SECONDS = 1.5

def calibrate_mic(audio_interface, seconds=2):
    print(f"\n[TEST] Calibrating microphone... (please stay quiet for {seconds} seconds)")
    stream = audio_interface.open(format=pyaudio.paInt16,
                                  channels=CHANNELS,
                                  rate=SAMPLE_RATE,
                                  input=True,
                                  frames_per_buffer=CHUNK_SIZE)
    
    chunks = int(SAMPLE_RATE / CHUNK_SIZE * seconds)
    rms_values = []
    for _ in range(chunks):
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        chunk_array = np.frombuffer(data, dtype=np.int16)
        rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
        rms_values.append(rms)

    stream.stop_stream()
    stream.close()

    ambient_mean = np.mean(rms_values)
    ambient_peak = np.max(rms_values)
    
    threshold = ambient_peak + 200
    if threshold < 300:
        threshold = 300
        
    print(f"[TEST] Mic calibrated — ambient mean={int(ambient_mean)}, peak={int(ambient_peak)} → speech threshold={int(threshold)}\n")
    return threshold

def listen(audio_interface, threshold):
    stream = audio_interface.open(format=pyaudio.paInt16,
                                  channels=CHANNELS,
                                  rate=SAMPLE_RATE,
                                  input=True,
                                  frames_per_buffer=CHUNK_SIZE)

    silence_chunks = int(SILENCE_DURATION * SAMPLE_RATE / CHUNK_SIZE)
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SIZE)

    preroll_size = int(PREROLL_SECONDS * SAMPLE_RATE / CHUNK_SIZE)
    preroll = deque(maxlen=preroll_size)

    frames = []
    speech_started = False
    silent_count = 0

    for _ in range(max_chunks):
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        chunk_array = np.frombuffer(data, dtype=np.int16)
        rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
        is_speech = rms >= threshold

        if is_speech:
            if not speech_started:
                speech_started = True
                frames.extend(list(preroll))
                print("  [mic] Speech detected")
            frames.append(data)
            silent_count = 0
        else:
            if not speech_started:
                preroll.append(data)
            else:
                frames.append(data)
                silent_count += 1
                if silent_count > silence_chunks:
                    break

    stream.stop_stream()
    stream.close()

    if not speech_started:
        return None

    duration = len(frames) * CHUNK_SIZE / SAMPLE_RATE
    if duration < MIN_RECORD_SECONDS:
        return None

    return frames

def transcribe(model, frames, audio_interface):
    audio_data = b''.join(frames)
    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio_np, beam_size=5, language="en", condition_on_previous_text=False)
    text = "".join([segment.text for segment in segments]).strip()
    return text if text else None

if __name__ == "__main__":
    print("=" * 60)
    print(" JARVIS Hearing Test Pipeline")
    print("=" * 60)

    print("[TEST] Loading openWakeWord model ('hey_jarvis')...")
    oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

    print("[TEST] Loading Faster-Whisper on CPU...")
    whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

    audio_interface = pyaudio.PyAudio()
    speech_threshold = calibrate_mic(audio_interface)

    print("[TEST] Pipeline online. Start speaking...")
    
    try:
        while True:
            frames = listen(audio_interface, speech_threshold)
            if frames is None:
                continue

            # -- WAKE WORD FILTER --
            has_wakeword = False
            oww_model.reset()
            max_score = 0.0
            for frame in frames:
                chunk_array = np.frombuffer(frame, dtype=np.int16)
                predictions = oww_model.predict(chunk_array)
                for score in predictions.values():
                    if score > max_score:
                        max_score = score
                if any(score > 0.05 for score in predictions.values()):
                    has_wakeword = True
                    break
            
            if not has_wakeword:
                print(f"  [DEBUG] openWakeWord score too low ({max_score:.2f}). Passing to Whisper anyway just in case...")

            # -- TRANSCRIBE --
            try:
                text = transcribe(whisper_model, frames, audio_interface)
            except Exception as e:
                print(f"[TEST] Transcription error: {e}")
                continue

            if text is None:
                continue

            clean_text = text.lower().replace('.', '').replace(',', '').replace('!', '').replace('?', '').replace('-', '').strip()
            print(f"  [DEBUG] Whisper heard: '{text}' -> Cleaned: '{clean_text}'")
            
            # Bulletproof check
            if "jarvis" not in clean_text:
                print("  [DEBUG] Ignored: Transcription did not contain 'Jarvis'.\n")
                continue

            # Case 2 check
            if clean_text in ["jarvis", "hey jarvis", "hi jarvis", "hello jarvis", "jarvis yes", "yes jarvis"]:
                print(f"\n[You] {text}")
                print("[JARVIS] Yes sir? (Case 2 Pause Detected)\n")
                
                print("[TEST] Listening for command...")
                cmd_frames = listen(audio_interface, speech_threshold)
                if cmd_frames:
                    cmd_text = transcribe(whisper_model, cmd_frames, audio_interface)
                    print(f"\n[You] {cmd_text}")
                    print("[JARVIS] (Processing Command)\n")
            else:
                print(f"\n[You] {text}")
                print("[JARVIS] (Processing Command)\n")

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        audio_interface.terminate()
