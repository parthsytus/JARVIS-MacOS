#!/usr/bin/env python3
"""
AEC Verification Test: Capture raw mic vs AEC-cleaned audio simultaneously.
Play music + speak during recording, then compare in Audacity.
"""

import pyaudio
import numpy as np
import wave
from core.jarvis_core import AECStreamWrapper, calibrate_mic


def main():
    audio = pyaudio.PyAudio()
    
    print("=" * 60)
    print("AEC Verification Test")
    print("=" * 60)
    print()
    print("SETUP REQUIRED:")
    print("1. Audio MIDI Setup -> Multi-Output Device ->")
    print("   Check BOTH your speakers/headphones AND 'BlackHole 2ch'")
    print("   Enable 'Drift Correction' on non-primary device")
    print("2. System Settings -> Sound -> Output -> Select 'Multi-Output Device'")
    print("3. Play music (Spotify/YouTube) - it will mirror into BlackHole")
    print()
    print("RECORDING: 15 seconds. Speak naturally while music plays.")
    print()
    input("Press Enter when ready to start recording...")
    
    # Calibrate first (uses AEC)
    print("\n[1/4] Calibrating microphone with AEC...")
    thresh, mean, peak = calibrate_mic(audio, duration=1.0, use_aec=True)
    print(f"    Threshold: {thresh} (ambient mean={mean:.0f}, peak={peak:.0f})")
    
    # Open raw mic stream (for comparison)
    print("[2/4] Opening raw mic stream...")
    raw_stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=1024
    )
    
    # Open AEC wrapper
    print("[3/4] Opening AEC stream (auto-detects BlackHole)...")
    aec_wrapper = AECStreamWrapper(audio)
    
    # Record
    print("[4/4] Recording for 15 seconds... SPEAK NOW!")
    print("    (Music should be playing through your speakers)")
    
    duration_sec = 15
    num_chunks = int(duration_sec * 16000 / 1024)
    
    raw_frames = []
    aec_frames = []
    
    for i in range(num_chunks):
        # Raw mic
        raw_data = raw_stream.read(1024, exception_on_overflow=False)
        raw_frames.append(raw_data)
        
        # AEC processed
        aec_data = aec_wrapper.read(1024, exception_on_overflow=False)
        aec_frames.append(aec_data)
        
        # Progress indicator
        if i % 50 == 0:
            elapsed = i * 1024 / 16000
            remaining = duration_sec - elapsed
            print(f"    {remaining:.1f}s remaining...", end="\r")
    
    print("\n    Done!")
    
    # Cleanup streams
    raw_stream.stop_stream()
    raw_stream.close()
    aec_wrapper.close()
    audio.terminate()
    
    # Save WAV files
    print("\nSaving WAV files...")
    
    for name, frames in [("raw_mic.wav", raw_frames), ("aec_cleaned.wav", aec_frames)]:
        with wave.open(name, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b''.join(frames))
        # Calculate RMS for info
        all_data = b''.join(frames)
        arr = np.frombuffer(all_data, dtype=np.int16)
        rms = np.sqrt(np.mean(arr.astype(np.float64) ** 2))
        print(f"  {name}: {len(frames)} chunks, {len(arr)/16000:.1f}s, RMS={rms:.1f}")
    
    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print()
    print("FILES CREATED:")
    print("  raw_mic.wav      - Direct microphone input (voice + music bleed)")
    print("  aec_cleaned.wav  - AEC processed (voice clear, music suppressed)")
    print()
    print("VERIFY IN AUDACITY:")
    print("1. Open both files in Audacity (File -> Import -> Audio)")
    print("2. Align tracks (they should be perfectly synced)")
    print("3. Select aec_cleaned track -> Effect -> Invert")
    print("4. Select both tracks -> Tracks -> Mix -> Mix and Render")
    print("5. Play result - you should hear ONLY the residual echo (music)")
    print("   The quieter the residual, the better the AEC works")
    print()
    print("EXPECTED: Music suppressed 20-30dB in aec_cleaned.wav")
    print("If music is still loud in aec_cleaned.wav, tune stream_delay_ms")


if __name__ == "__main__":
    main()