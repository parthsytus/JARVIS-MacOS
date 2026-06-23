import os
import time
import wave
import soundfile as sf
import sounddevice as sd

def play_audio(filename):
    """Play the generated WAV file using sounddevice."""
    try:
        data, fs = sf.read(filename)
        sd.play(data, fs)
        sd.wait()
    except Exception as e:
        print(f"  [!] Error playing audio: {e}")

def main():
    print("Initializing Piper TTS (Hindi Native Model) on CPU...")
    start_init = time.time()
    
    try:
        from piper.voice import PiperVoice
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        model_path = os.path.join(_project_root, "models", "piper", "hi_IN-priyamvada-medium.onnx")
        voice = PiperVoice.load(model_path)
        
        init_time = (time.time() - start_init) * 1000
        print(f"Piper Hindi model loaded successfully in {init_time:.2f} ms")
        
    except ImportError as e:
        print(f"Error importing modules: {e}")
        print("Make sure to run: pip install piper-tts deep-translator")
        return
    except Exception as e:
        print(f"Failed to load Piper TTS: {e}")
        return

    # These are written in Roman characters as you requested.
    test_sentences = [
        "computer turn on karo",
        "haan bhai ye ho jayega",
        "aaj ka kaam complete ho gaya",
        "jarvis volume badhao",
        "system is ready and online"
    ]

    total_start_time = time.time()
    output_file = os.path.join(_project_root, "piper_hindi_test_output.wav")

    import requests
    import json

    for i, text in enumerate(test_sentences):
        print(f"\n--- Sentence {i+1}/{len(test_sentences)} ---")
        print(f"Original Text (Roman): '{text}'")
        
        # 100% LOCAL TRICK: Ask your locally running Ollama (Gemma) to translate it to Devanagari!
        # No internet required, no paid APIs.
        try:
            prompt = f"Translate the following Hinglish or English sentence to pure Hindi written in Devanagari script. Reply ONLY with the Devanagari text, nothing else. Sentence: '{text}'"
            response = requests.post("http://localhost:11434/api/generate", json={
                "model": "gemma3:4b",
                "prompt": prompt,
                "stream": False
            })
            hindi_text = response.json()["response"].strip()
            # Clean up any quotes
            hindi_text = hindi_text.replace('"', '').replace("'", "")
            print(f"Ollama Local Translation (Devanagari): '{hindi_text}'")
        except Exception as e:
            print(f"Failed to reach local Ollama. Make sure Ollama is running! Error: {e}")
            hindi_text = text # Fallback
            
        start_tts = time.time()
        try:
            # Pass the perfect DEVANAGARI text directly
            audio_stream = voice.synthesize(hindi_text)
            
            # Combine all chunks into one byte stream
            pcm = b"".join([chunk.audio_int16_bytes for chunk in audio_stream])
            
            tts_time_ms = (time.time() - start_tts) * 1000
            print(f"TTS Generation Time: {tts_time_ms:.2f} ms")
            
            # Play it back directly from memory using sounddevice
            import numpy as np
            audio_np = np.frombuffer(pcm, dtype=np.int16)
            sd.play(audio_np, samplerate=voice.config.sample_rate)
            sd.wait()
            
        except Exception as e:
            print(f"Error generating or playing TTS for this sentence: {e}")
            
        time.sleep(1.0)

    total_time_ms = (time.time() - total_start_time) * 1000
    print(f"\n=================================")
    print(f"Total testing time (including audio playback): {total_time_ms:.2f} ms")
    
    if os.path.exists(output_file):
        try:
            os.remove(output_file)
        except:
            pass

if __name__ == "__main__":
    main()
