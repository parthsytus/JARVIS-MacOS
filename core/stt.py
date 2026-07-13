import time
import numpy as np
import logging
import threading

# Setup logging
logger = logging.getLogger("JARVIS.STT")
logger.setLevel(logging.DEBUG)

# Global lock to serialize MLX GPU operations (STT and TTS)
mlx_lock = threading.Lock()


def frames_to_array(frames):
    """Convert raw PCM frames to float32 numpy array."""
    raw_bytes = b''.join(frames)
    return np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0


class STTEngine:
    def __init__(self, model_name=None):
        from config.config import WHISPER_MODEL
        self.model_name = model_name or WHISPER_MODEL
        logger.debug(f"Loading MLX Whisper model ({self.model_name})...")
        import mlx_whisper
        self._mlx_whisper = mlx_whisper
        # Warm up — triggers model download + compilation on first run
        # This installed build of mlx_whisper raises NotImplementedError if beam_size
        # is passed at all (even 1) — omit the argument to get greedy decoding.
        dummy = np.zeros(16000, dtype=np.float32)  # 1s of silence
        with mlx_lock:
            mlx_whisper.transcribe(dummy, path_or_hf_repo=self.model_name)
        logger.debug("MLX Whisper model loaded successfully.")

    def transcribe(self, audio, sample_rate: int = 16000, initial_prompt: str = None):
        """Transcribe raw numpy float32 audio array using MLX Whisper.

        Accepts audio directly in memory — no temp files needed.
        Auto-detects language (English, Hindi, Hinglish all work).
        Also accepts list of raw PCM frames for convenience.
        
        Note: This build of mlx_whisper raises NotImplementedError if beam_size
        is passed at all (any value). Omitting the kwarg gives greedy decoding.
        """
        if audio is None or len(audio) == 0:
            return "", "auto"

        # If audio is frames (list of bytes), convert to array
        if isinstance(audio, list):
            audio = frames_to_array(audio)

        # Gentle normalization: target RMS 0.1, max gain 5x
        rms = np.sqrt(np.mean(audio ** 2))
        if rms > 0.0:
            gain = min(0.1 / rms, 5.0)
            audio = audio * gain
        audio = np.clip(audio, -1.0, 1.0)

        t_start = time.time()
        with mlx_lock:
            result = self._mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=self.model_name,
                initial_prompt=initial_prompt,
                language=None,  # Auto-detect (handles Hindi/English/Hinglish)
                condition_on_previous_text=False,  # Prevents hallucination loops
                compression_ratio_threshold=2.4,  # Filter hallucinated repeated text
                # No beam_size kwarg — this build only supports greedy decoding,
                # and passing beam_size at all (any value) raises NotImplementedError.
            )
        t_end = time.time()

        latency_ms = int((t_end - t_start) * 1000)
        logger.debug(f"Transcription latency: {latency_ms} ms")

        text = result.get("text", "").strip()
        return text, "auto"
