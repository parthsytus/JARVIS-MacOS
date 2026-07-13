# ==========================================================
# JARVIS — Lazy Loaders
# Load heavy models only when first needed, not at startup.
# Saves ~1.4 GB RAM at idle.
# ==========================================================

import threading
import logging
import collections
import numpy as np
import soxr  # proper anti-aliased streaming resampler

logger = logging.getLogger("JARVIS.LazyLoaders")

# --- AEC Reference Buffer ---
# Holds 10ms int16 mono frames @ 16kHz — the exact audio just sent to output,
# time-delayed so AECStreamWrapper sees them in sync with when the mic
# actually picks up the echo.
AEC_REF_FRAME_SIZE = 160          # 10ms @ 16kHz — must match pywebrtc_audio's block size
AEC_MEASURED_DELAY_MS = 1200      # empirically measured BT round trip — re-tune after this change
AEC_DELAY_FRAMES = AEC_MEASURED_DELAY_MS // 10

_aec_ref_queue = collections.deque(maxlen=AEC_DELAY_FRAMES * 3)  # safety cap
_aec_leftover = np.zeros(0, dtype=np.int16)
_kokoro_resampler = None  # created lazily once KOKORO_PLAYBACK_SAMPLE_RATE is known


def _push_aec_reference(audio_f32, src_rate):
    """Resample TTS output to 16kHz mono int16 and enqueue as 10ms frames."""
    global _aec_leftover, _kokoro_resampler
    if _kokoro_resampler is None:
        from config.config import SAMPLE_RATE
        _kokoro_resampler = soxr.ResampleStream(src_rate, SAMPLE_RATE, 1, dtype='float32')

    resampled = _kokoro_resampler.resample_chunk(audio_f32, last=False)
    pcm16 = np.clip(resampled * 32767.0, -32768, 32767).astype(np.int16)

    buf = np.concatenate([_aec_leftover, pcm16])
    n_frames = len(buf) // AEC_REF_FRAME_SIZE
    for i in range(n_frames):
        _aec_ref_queue.append(buf[i * AEC_REF_FRAME_SIZE:(i + 1) * AEC_REF_FRAME_SIZE].copy())
    _aec_leftover = buf[n_frames * AEC_REF_FRAME_SIZE:]


def get_aec_reference_frame():
    """Pop the oldest delayed reference frame, or zeros if nothing is playing
    yet or not enough has buffered to match the measured transport delay."""
    if len(_aec_ref_queue) > AEC_DELAY_FRAMES:
        return _aec_ref_queue.popleft()
    return np.zeros(AEC_REF_FRAME_SIZE, dtype=np.int16)


# --- Silero VAD ---
_vad_model = None
_vad_lock = threading.Lock()
_vad_loaded = False

def get_vad_model():
    """Lazy load Silero VAD model."""
    global _vad_model, _vad_loaded
    if _vad_loaded:
        return _vad_model
    
    with _vad_lock:
        if _vad_loaded:
            return _vad_model
        
        logger.debug("Loading Silero VAD...")
        try:
            import torch
            _vad_model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-vad', 
                model='silero_vad', 
                force_reload=False, 
                trust_repo=True
            )
            _vad_loaded = True
            logger.debug("Silero VAD loaded.")
        except Exception as e:
            logger.warning(f"Silero VAD load failed: {e}. Falling back to RMS.")
            _vad_model = None
            _vad_loaded = True
        return _vad_model


# --- MLX Whisper STT ---
_stt_engine = None
_stt_lock = threading.Lock()
_stt_loaded = False

def get_stt_engine():
    """Lazy load MLX Whisper STT engine."""
    global _stt_engine, _stt_loaded
    if _stt_loaded:
        return _stt_engine
    
    with _stt_lock:
        if _stt_loaded:
            return _stt_engine
        
        logger.debug("Loading MLX Whisper STT...")
        try:
            from core.stt import STTEngine
            from config.config import WHISPER_MODEL
            _stt_engine = STTEngine(WHISPER_MODEL)
            _stt_loaded = True
            logger.debug("MLX Whisper STT loaded.")
        except Exception as e:
            logger.error(f"Failed to load MLX Whisper STT: {e}")
            raise
        return _stt_engine


# --- Kokoro TTS (KPipeline + sounddevice, in-memory, two-thread pipeline) ---
_tts_synth_thread = None
_tts_playback_thread = None
_tts_init_lock = threading.Lock()
_tts_initialized = False

_sentence_queue = None
_audio_queue = None
_kpipeline = None
_playback_stream = None

# Hinglish pronunciation fix: respell common words for English G2P
_HINGLISH_REPLACEMENTS = {
    "accha": "ah-cha",
    "achha": "ah-cha",
    "bhai": "bh-eye",
    "bhaiya": "bh-eye-ya",
    "yaar": "yar",
    "matlab": "mut-lub",
    "theek": "thayk",
    "thik": "thick",
    "haan": "han",
    "nahi": "na-hee",
    "nahiin": "na-heen",
    "kya": "kyaa",
    "kyun": "kyoon",
    "kaise": "kai-say",
    "kaisa": "kai-sa",
    "kaun": "kaun",
    "kahan": "ka-han",
    "kab": "kub",
    "kitna": "kit-na",
    "bahut": "buh-hut",
    "zaroor": "za-roor",
    "pakka": "puck-ka",
    "sahi": "sa-hee",
    "galat": "guh-lut",
    "shuru": "shoo-roo",
    "khatam": "khut-tum",
    "chalo": "chuh-lo",
    "bas": "bus",
    "abhi": "ub-hee",
    "baad": "baad",
    "pehle": "pay-hlay",
    "baadmein": "bad-main",
    "ek": "ek",
    "do": "do",
    "teen": "teen",
    "chaar": "char",
    "paanch": "panch",
    "chhah": "chhah",
    "saat": "saat",
    "aath": "aath",
    "nau": "now",
    "das": "dus",
}

def _apply_hinglish_fixes(text: str) -> str:
    """Replace common Hinglish words with respelled versions for English G2P."""
    result = text
    for orig, repl in _HINGLISH_REPLACEMENTS.items():
        # Word-boundary replace (case-insensitive)
        import re
        result = re.sub(rf'\b{re.escape(orig)}\b', repl, result, flags=re.IGNORECASE)
    return result

def ensure_tts_initialized():
    """Lazy initialize Kokoro TTS using KPipeline + sounddevice."""
    global _tts_synth_thread, _tts_playback_thread, _tts_initialized
    global _sentence_queue, _audio_queue, _kpipeline, _playback_stream
    
    if _tts_initialized:
        return
    
    with _tts_init_lock:
        if _tts_initialized:
            return
        
        logger.debug("Initializing Kokoro TTS (KPipeline + sounddevice)...")
        try:
            import queue as _queue_mod
            import numpy as np
            import sounddevice as sd
            from kokoro import KPipeline
            from config.config import KOKORO_VOICE, KOKORO_SAMPLE_RATE, KOKORO_PLAYBACK_SAMPLE_RATE
            
            _sentence_queue = _queue_mod.Queue()
            _audio_queue = _queue_mod.Queue()
            
            # Load KPipeline once, keep it alive for the session
            logger.debug("Loading Kokoro KPipeline...")
            _kpipeline = KPipeline(lang_code='b')  # 'b' = British English (bm_george)
            
            # Warm-up call — pay first-call cost now, not on first user sentence
            logger.debug("Warming up KPipeline...")
            for _ in _kpipeline("Warming up.", voice=KOKORO_VOICE, speed=1.2):
                pass
            logger.debug("KPipeline warm-up complete.")
            
            # Initialize sounddevice output stream (kept open)
            _playback_stream = sd.OutputStream(
                samplerate=KOKORO_PLAYBACK_SAMPLE_RATE,
                channels=1,
                dtype='float32'
            )
            _playback_stream.start()
            
            def _synth_worker():
                """Thread 1: Pull sentences, synthesize to numpy arrays, push to audio queue."""
                while True:
                    text = _sentence_queue.get()
                    if text is None:
                        _sentence_queue.task_done()
                        break
                    try:
                        # Apply Hinglish pronunciation fixes before synthesis
                        text = _apply_hinglish_fixes(text)
                        
                        # Synthesize in-memory (no temp files)
                        chunks = []
                        for _, _, audio in _kpipeline(text, voice=KOKORO_VOICE, speed=1.2):
                            # Convert torch.Tensor to numpy if needed
                            if hasattr(audio, "numpy"):
                                audio = audio.detach().cpu().numpy()
                            chunks.append(audio)
                        full_audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
                        _audio_queue.put(full_audio)
                    except Exception as e:
                        logger.error(f"TTS Synthesis Error: {e}")
                    finally:
                        _sentence_queue.task_done()
            
            def _playback_worker():
                """Thread 2: Pull audio arrays, stream directly to sounddevice."""
                from config.config import KOKORO_PLAYBACK_SAMPLE_RATE
                while True:
                    audio = _audio_queue.get()
                    if audio is None:
                        _audio_queue.task_done()
                        break
                    try:
                        # Ensure correct dtype and shape for sounddevice
                        if audio.dtype != np.float32:
                            audio = audio.astype(np.float32)
                        _push_aec_reference(audio, KOKORO_PLAYBACK_SAMPLE_RATE)
                        _playback_stream.write(audio)
                    except Exception as e:
                        logger.error(f"Audio Playback Error: {e}")
                    finally:
                        _audio_queue.task_done()
            
            # Store queues as module globals for speak() to use
            globals()['_sentence_queue'] = _sentence_queue
            globals()['_audio_queue'] = _audio_queue
            
            _tts_synth_thread = threading.Thread(target=_synth_worker, daemon=True)
            _tts_playback_thread = threading.Thread(target=_playback_worker, daemon=True)
            _tts_synth_thread.start()
            _tts_playback_thread.start()
            
            _tts_initialized = True
            logger.debug("Kokoro TTS initialized (KPipeline + sounddevice).")
        except Exception as e:
            logger.error(f"Failed to initialize TTS: {e}")
            raise


def speak(text):
    """Queue text to be spoken asynchronously (initializes TTS on first call)."""
    ensure_tts_initialized()
    _sentence_queue.put(text)


def wait_for_speech():
    """Block until all queued text is spoken."""
    ensure_tts_initialized()
    _sentence_queue.join()
    _audio_queue.join()


# --- Memory System ---
_memory_manager = None
_memory_lock = threading.Lock()
_memory_initialized = False

def get_memory_manager():
    """Lazy initialize MemoryManager."""
    global _memory_manager, _memory_initialized
    if _memory_initialized:
        return _memory_manager
    
    with _memory_lock:
        if _memory_initialized:
            return _memory_manager
        
        logger.debug("Initializing MemoryManager...")
        try:
            from memory.memory_manager import MemoryManager
            from config.config import (
                JARVIS_ROOT, OLLAMA_URL, OLLAMA_MODEL,
                MEMORY_EMBEDDING_MODEL, MEMORY_DECAY_TAU, MEMORY_CONTEXT_BUDGET
            )
            
            _memory_manager = MemoryManager(
                jarvis_root=JARVIS_ROOT,
                ollama_url=OLLAMA_URL,
                ollama_model=OLLAMA_MODEL,
                embedding_model=MEMORY_EMBEDDING_MODEL,
                decay_tau_days=MEMORY_DECAY_TAU,
                context_budget_tokens=MEMORY_CONTEXT_BUDGET,
            )
            _memory_initialized = True
            logger.debug("MemoryManager initialized.")
        except Exception as e:
            logger.warning(f"Memory system failed to initialize: {e}")
            _memory_manager = None
            _memory_initialized = True
        return _memory_manager


# --- Consolidated getter for first-use initialization ---
_first_use_done = False
_first_use_lock = threading.Lock()

def ensure_first_use_initialized():
    """Initialize all heavy components on first actual use (first user query)."""
    global _first_use_done
    if _first_use_done:
        return
    
    with _first_use_lock:
        if _first_use_done:
            return
        
        logger.info("=== FIRST USE INITIALIZATION ===")
        
        # Load VAD
        get_vad_model()
        
        # Load STT
        get_stt_engine()
        
        # Initialize TTS
        ensure_tts_initialized()
        
        # Initialize Memory
        get_memory_manager()
        
        _first_use_done = True
        logger.info("=== FIRST USE INITIALIZATION COMPLETE ===")


# --- Cleanup at shutdown ---
def cleanup_all():
    """Call at shutdown to clean up resources."""
    global _vad_loaded, _stt_loaded, _tts_initialized, _memory_initialized
    
    # Stop TTS queues (new KPipeline + sounddevice)
    try:
        globals_dict = globals()
        if '_sentence_queue' in globals_dict and '_audio_queue' in globals_dict:
            globals_dict['_sentence_queue'].put(None)
            globals_dict['_audio_queue'].put(None)
            globals_dict['_sentence_queue'].join()
            globals_dict['_audio_queue'].join()
    except Exception:
        pass
    
    # Also stop old TTS queues if they exist (backward compat)
    try:
        import core
        if hasattr(core, '_global_text_q'):
            core._global_text_q.put(None)
            core._global_audio_q.put(None)
            core._global_text_q.join()
            core._global_audio_q.join()
    except Exception:
        pass
    
    # Unload complex model if loaded
    unload_complex_model()
    
    # Stop sounddevice stream if running
    try:
        globals_dict = globals()
        if '_playback_stream' in globals_dict and globals_dict['_playback_stream']:
            globals_dict['_playback_stream'].stop()
            globals_dict['_playback_stream'].close()
    except Exception:
        pass
    
    _vad_loaded = False
    _stt_loaded = False
    _tts_initialized = False
    _memory_initialized = False
    
    logger.info("All lazy loaders cleaned up.")


# ============================================================
# DUAL MODEL MANAGER
# ============================================================
_complex_model_loaded = False
_complex_model_lock = threading.Lock()

def is_complex_model_loaded():
    """Check if complex model is currently loaded in Ollama."""
    global _complex_model_loaded
    return _complex_model_loaded

def load_complex_model():
    """Load the complex model (gemma4:12b) into Ollama."""
    global _complex_model_loaded
    import requests
    from config.config import OLLAMA_URL, COMPLEX_MODEL
    
    with _complex_model_lock:
        if _complex_model_loaded:
            return True
        
        logger.info(f"Loading complex model: {COMPLEX_MODEL}...")
        try:
            # Use a minimal request to load the model with keep_alive: -1 temporarily
            payload = {
                "model": COMPLEX_MODEL,
                "messages": [{"role": "user", "content": "ready"}],
                "stream": False,
                "keep_alive": -1,  # Keep loaded
                "options": {"num_predict": 1}
            }
            response = requests.post(OLLAMA_URL, json=payload, timeout=60)
            response.raise_for_status()
            _complex_model_loaded = True
            logger.info(f"Complex model {COMPLEX_MODEL} loaded and ready.")
            return True
        except Exception as e:
            logger.error(f"Failed to load complex model: {e}")
            return False

def unload_complex_model():
    """Unload the complex model from Ollama (set keep_alive: 0)."""
    global _complex_model_loaded
    import requests
    from config.config import OLLAMA_URL, COMPLEX_MODEL
    
    with _complex_model_lock:
        if not _complex_model_loaded:
            return True
        
        logger.info(f"Unloading complex model: {COMPLEX_MODEL}...")
        try:
            # Send empty request with keep_alive: 0 to unload
            payload = {
                "model": COMPLEX_MODEL,
                "keep_alive": 0
            }
            requests.post(OLLAMA_URL.replace('/api/chat', '/api/generate'), json=payload, timeout=10)
            _complex_model_loaded = False
            logger.info(f"Complex model {COMPLEX_MODEL} unloaded.")
            return True
        except Exception as e:
            logger.warning(f"Failed to unload complex model: {e}")
            return False

def call_complex_model(messages, tools=None, stream=True, think=True):
    """Call the complex model with full context and tools."""
    import requests
    import json
    from config.config import OLLAMA_URL, COMPLEX_MODEL, COMPLEX_NUM_CTX, COMPLEX_NUM_PREDICT, COMPLEX_KEEP_ALIVE
    
    # Ensure complex model is loaded
    if not load_complex_model():
        return None, "Failed to load complex model"
    
    payload = {
        "model": COMPLEX_MODEL,
        "messages": messages,
        "stream": stream,
        "think": think,
        "keep_alive": COMPLEX_KEEP_ALIVE,
        "options": {
            "num_ctx": COMPLEX_NUM_CTX,
            "num_predict": COMPLEX_NUM_PREDICT,
            "num_gpu": 99,
            "temperature": 0.3
        }
    }
    
    if tools:
        payload["tools"] = tools
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=300, stream=stream)
        response.raise_for_status()
        return response, None
    except Exception as e:
        logger.error(f"Complex model call failed: {e}")
        return None, str(e)


def call_fast_model(messages, tools=None, stream=False):
    """Call the fast resident model (Qwen 4B) for quick tasks like decomposition."""
    import requests
    from config.config import OLLAMA_URL, FAST_MODEL, FAST_NUM_CTX, FAST_NUM_PREDICT, FAST_KEEP_ALIVE
    
    payload = {
        "model": FAST_MODEL,
        "messages": messages,
        "stream": stream,
        "think": False,  # Fast model doesn't need thinking for simple tasks
        "keep_alive": FAST_KEEP_ALIVE,
        "options": {
            "num_ctx": FAST_NUM_CTX,
            "num_predict": FAST_NUM_PREDICT,
            "num_gpu": 99,
            "temperature": 0.3
        }
    }
    
    if tools:
        payload["tools"] = tools
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60, stream=stream)
        response.raise_for_status()
        return response, None
    except Exception as e:
        logger.error(f"Fast model call failed: {e}")
        return None, str(e)