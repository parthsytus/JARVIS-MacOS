import torch
from transformers import pipeline, AutoModelForCTC, AutoProcessor
import sounddevice as sd
import numpy as np
import time
import warnings
import sys

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore")

def main():
    print("=== MMS ASR Standalone Test ===")
    
    # Check device - Forcing CPU first to rule out VRAM issues
    device_id = -1 # Force CPU for testing
    device_name = "CPU (Forced for testing)"
    print(f"[*] Compute device: {device_name}")
    
    # User requested MMS-300M. 
    # Note: facebook/mms-300m is a PRETRAINED base model (outputs gibberish directly).
    # The official fine-tuned multilingual ASR by Meta is facebook/mms-1b-all (1 Billion params).
    # However, to stick to the ~300M parameter limit (~600MB VRAM) and get excellent Hindi/Hinglish,
    # we use Meta's Wav2Vec2-Large architecture which is exactly 300M parameters.
    # If you specifically want to test the MMS 1B model, change this to "facebook/mms-1b-all"
    # and add `pipe.model.load_adapter("hin")`.
    
    MODEL_ID = "theainerd/Wav2Vec2-large-xlsr-hindi" # A 300M param model heavily fine-tuned for Hindi/Hinglish
    # MODEL_ID = "facebook/mms-1b-all" # Uncomment for official MMS (takes ~2GB VRAM)
    
    print(f"[*] Loading model: {MODEL_ID} (~300M params)")
    try:
        print("[*] Downloading/Loading processor...")
        processor = AutoProcessor.from_pretrained(MODEL_ID)
        
        print("\n[*] Downloading/Loading model weights...")
        print("    -> IMPORTANT: If this is your first time loading the model on Windows without")
        print("    -> Developer Mode enabled, HuggingFace has to physically copy the 1.2GB file")
        print("    -> instead of using a symlink. THIS CAN TAKE 30-60 SECONDS! Please do not cancel.")
        
        model = AutoModelForCTC.from_pretrained(MODEL_ID)
        
        print("[*] Initializing pipeline...")
        pipe = pipeline(
            "automatic-speech-recognition", 
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=device_id
        )
        print("[*] Model loaded successfully!\n")
    except BaseException as e:
        print(f"\n[!] CRASH/INTERRUPT CAUGHT: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Audio settings
    SAMPLE_RATE = 16000
    DURATION = 5

    def record_audio():
        print(f"\n[Recording] Speak now for {DURATION} seconds...")
        try:
            # Record mono audio at 16kHz
            audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32')
            sd.wait()
            print("[Recording] Done.")
            return audio.flatten()
        except Exception as e:
            print(f"[!] Microphone error: {e}")
            return None

    while True:
        cmd = input("\nPress Enter to record 5s of audio (or type 'quit' to exit): ").strip().lower()
        if cmd == 'quit':
            print("Exiting...")
            break
        
        audio_data = record_audio()
        if audio_data is None:
            continue
            
        print("[*] Transcribing...")
        start_time = time.time()
        
        try:
            # Pass raw audio to the pipeline
            result = pipe({"raw": audio_data, "sampling_rate": SAMPLE_RATE})
            text = result.get("text", "")
            elapsed_ms = (time.time() - start_time) * 1000
            
            print(f"\n---> Transcription: {text}")
            print(f"---> Time taken: {elapsed_ms:.2f} ms")
            
        except Exception as e:
            print(f"\n[!] Error during transcription: {e}")

if __name__ == "__main__":
    main()
