import os
import time
import sys

def main():
    # 1. Import
    try:
        from kokoro_mlx import KokoroTTS
        import soundfile as sf
    except ImportError as e:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print(f"Details: Required package import failed: {e}")
        print("==================================================")
        sys.exit(1)

    print("Import successful. Loading model...")

    # 2. Load model and time it
    start_load = time.time()
    try:
        # Load model via KokoroTTS.from_pretrained()
        tts = KokoroTTS.from_pretrained()
    except Exception as e:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print(f"Details: Model loading failed: {e}")
        print("==================================================")
        sys.exit(1)
    end_load = time.time()
    load_time = end_load - start_load
    print(f"Model loaded in {load_time:.4f} seconds (includes first-run download if applicable).")

    # 3. Check voices and assert bm_george is present
    try:
        voices = tts.list_voices()
        print(f"Available voices: {voices}")
    except Exception as e:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print(f"Details: Failed to list voices: {e}")
        print("==================================================")
        sys.exit(1)

    if "bm_george" not in voices:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print("Details: voice 'bm_george' is not present in list_voices()!")
        print("==================================================")
        sys.exit(1)

    print("Assertion passed: 'bm_george' voice is available.")

    text = "good morning sir, i ran a quick check for all the system setting and configurations, all settings seem nominal and everything is working just right, I am jarvis, a personal assistant for you made by Parth Sharma. Would you like me to help you with anything sir?"
    voice = "bm_george"

    # 4. Cold synthesis
    print("Starting cold synthesis...")
    start_cold = time.time()
    try:
        result_cold = tts.generate(text, voice=voice)
    except Exception as e:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print(f"Details: Cold synthesis failed: {e}")
        print("==================================================")
        sys.exit(1)
    end_cold = time.time()
    cold_time = end_cold - start_cold
    print(f"Cold synthesis completed in {cold_time:.4f} seconds.")

    # 5. Warm synthesis
    print("Starting warm synthesis...")
    start_warm = time.time()
    try:
        result_warm = tts.generate(text, voice=voice)
    except Exception as e:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print(f"Details: Warm synthesis failed: {e}")
        print("==================================================")
        sys.exit(1)
    end_warm = time.time()
    warm_time = end_warm - start_warm
    print(f"Warm synthesis completed in {warm_time:.4f} seconds.")

    # 6. Save output
    output_dir = "core/test/output"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "kokoro_test.wav")
    
    try:
        sf.write(output_path, result_warm.audio, 24000)
        print(f"Saved warm-run output to {output_path}")
    except Exception as e:
        print("\n==================================================")
        print("SUMMARY")
        print("==================================================")
        print("Status: FAIL")
        print(f"Details: Failed to save audio file: {e}")
        print("==================================================")
        sys.exit(1)

    # 7. Compute real-time factor for warm run
    audio_duration = getattr(result_warm, "duration", None)
    if audio_duration is None or audio_duration <= 0:
        audio_duration = len(result_warm.audio) / 24000.0
    
    rtf = warm_time / audio_duration

    # 8. Print PASS/FAIL summary block
    print("\n==================================================")
    print("SUMMARY")
    print("==================================================")
    print("Status: PASS")
    print(f"Model Load Time: {load_time:.4f} seconds")
    print(f"Cold Synthesis Time: {cold_time:.4f} seconds")
    print(f"Warm Synthesis Time: {warm_time:.4f} seconds")
    print(f"Real-Time Factor: {rtf:.4f}")
    print(f"Output File Path: {output_path}")
    print("==================================================")

if __name__ == "__main__":
    main()
