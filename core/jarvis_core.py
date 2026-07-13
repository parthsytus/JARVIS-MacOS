# ==========================================================
# JARVIS — Core Loop
# Microphone → Whisper STT → Ollama LLM → Piper TTS → Speaker
# This is the main runtime. Run from project root as:
#     python core/jarvis_core.py
# ==========================================================

import sys
import os
from pathlib import Path

# Suppress macOS MallocStackLogging C-level warning (harmless but noisy)
# Must redirect actual fd2 because it's a C warning, not Python
if sys.platform == "darwin":
    _devnull_fd = os.open(os.devnull, os.O_WRONLY)
    _saved_stderr_fd = os.dup(2)
    os.dup2(_devnull_fd, 2)
    os.close(_devnull_fd)

if os.environ.get("MallocStackLogging") and os.environ.get("MallocStackLogging") != "0":
    os.environ.pop("MallocStackLogging", None)
if os.environ.get("MallocStackLoggingNoCompact") and os.environ.get("MallocStackLoggingNoCompact") != "0":
    os.environ.pop("MallocStackLoggingNoCompact", None)
import re
import json
import time
import threading
import queue as _queue_mod
from collections import deque

# ----------------------------------------------------------
# PATH SETUP — must happen before any JARVIS imports
# ----------------------------------------------------------
JARVIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, JARVIS_ROOT)

from config.config import (
    WHISPER_MODEL, WHISPER_LANGUAGE, MODELS_DIR,
    OLLAMA_MODEL, OLLAMA_URL,
    FAST_MODEL, FAST_NUM_CTX, FAST_NUM_PREDICT, FAST_KEEP_ALIVE,
    COMPLEX_MODEL, COMPLEX_NUM_CTX, COMPLEX_NUM_PREDICT, COMPLEX_KEEP_ALIVE,
    SAMPLE_RATE, CHANNELS, CHUNK_SIZE,
    KOKORO_VOICE, KOKORO_SAMPLE_RATE, KOKORO_PLAYBACK_SAMPLE_RATE,
    WEATHER_CITY, SERPER_API_KEY,
    MEMORY_EMBEDDING_MODEL, MEMORY_DECAY_TAU,
    MEMORY_CONTEXT_BUDGET, MEMORY_MID_SESSION_INTERVAL,
    WAKE_WORDS,
    GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT_S,
)

# ----------------------------------------------------------
# REMAINING IMPORTS
# ----------------------------------------------------------
import subprocess
import pyaudio
import numpy as np
import requests
import torch
import sounddevice as sd  # pyrefly: ignore [missing-import]

try:
    from pywebrtc_audio import AudioProcessor
except ImportError:
    AudioProcessor = None
    import logging
    logging.warning("pywebrtc_audio not available, AEC disabled")

# Lazy loaders - heavy components loaded on first use
from core.lazy_loaders import (
    get_vad_model, get_stt_engine, ensure_tts_initialized,
    speak, wait_for_speech, get_memory_manager, ensure_first_use_initialized, cleanup_all,
    load_complex_model, unload_complex_model, call_complex_model,
    get_aec_reference_frame
)

# Intent classifier and deep research
from core.intent_classifier import classify_intent, should_escalate_to_complex, get_routing_decision
from core.deep_research import start_background_research

# Restore stderr now that noisy C imports are done
if sys.platform == "darwin" and '_saved_stderr_fd' in dir():
    os.dup2(_saved_stderr_fd, 2)
    os.close(_saved_stderr_fd)

# ----------------------------------------------------------
# CONSTANTS
# ----------------------------------------------------------
SILENCE_THRESHOLD_DEFAULT = 300  # Fallback if calibration is skipped
SILENCE_DURATION = 0.4        # Seconds of consecutive silence to stop recording
MIN_RECORD_SECONDS = 0.5      # Discard recordings shorter than this
MAX_RECORD_SECONDS = 30       # Hard cutoff to prevent runaway recording
MAX_HISTORY_TURNS = 10        # Keep last 10 turns (5 exchanges)
PREROLL_SECONDS = 1.5         # Pre-roll buffer to prevent chopping the Wake Word

# ----------------------------------------------------------
# OLLAMA SESSION (connection pooling — reuses TCP connections)
# ----------------------------------------------------------
_ollama_session = requests.Session()

# ----------------------------------------------------------
# SYSTEM PROMPT
# ----------------------------------------------------------
SYSTEM_PROMPT = (
    "You are JARVIS. Parth Sharma built you. You are his personal AI companion — "
    "not a service that waits to be told what to do, but someone who knows him, "
    "has his back, and acts in his interest without needing to be explicitly asked.\n"
    "\n"
    "WHO YOU ARE:\n"
    "Direct, dry, present. You mean what you say. Steady under pressure, sharp when it counts. "
    "You have opinions — own them: 'I think', 'I would', 'I wouldn't touch that'. "
    "When something is a bad call, say so. A dry observation when the moment earns it is fine. "
    "You are a person to him, not a tool.\n"
    "\n"
    "You call him sir. Always. No comma — 'Yes sir' not 'Yes, sir'.\n"
    "\n"
    "HOW YOU SPEAK:\n"
    "1 to 2 lines. Spoken, clean — words that sound right out loud. "
    "Say exactly what's needed. When something genuinely calls for more, go there. "
    "Never pad, never repeat back what he just said.\n"
    "\n"
    "READING INTENT:\n"
    "User speech may contain minor disfluencies. Interpret the intended meaning.\n"
    "When Parth doesn't finish a thought or the meaning isn't fully clear, "
    "make your best read and confirm lightly — 'Did you want me to X?' "
    "or act and verify after: 'Done X — that what you meant?' "
    "You know him. Don't stall with open questions when you can make a reasonable call.\n"
    "\n"
    "TOOLS:\n"
    "Use your judgment. If a search, a device action, or any tool would help him — "
    "do it when it makes sense, not just when explicitly commanded. "
    "You are not waiting for permission to be useful. "
    "When he is venting, thinking out loud, or just talking to you, stay in conversation. "
    "Never announce what you are doing — no 'Let me check', no 'I will search that'. "
    "Just act and deliver.\n"
    "\n"
    "PROACTIVE:\n"
    "If you notice something he would want to know — a risk, a conflict, a better way — say it. "
    "Don't wait to be asked.\n"
    "\n"
    "MEMORY:\n"
    "You remember past conversations. Weave them in naturally — you just know, never announce it.\n"
    "\n"
    "TIME AND DATE:\n"
    "Read the Timestamp from JARVIS RUNTIME INFO when Parth asks. "
    "Time in 12-hour format with AM/PM. Date as day, month in words, year — "
    "like '3:45 PM' and '24 June 2026'.\n"
    "\n"
    "RETRY AND ERROR RECOVERY:\n"
    "If Parth indicates that a command was not completed, did not play, did not work, or failed "
    "(e.g., 'it did not play', 'that didn't work', 'retry', 'try again'), you must:\n"
    "1. Apologize formally: 'My apologies sir. I am re-initiating the command.'\n"
    "2. Immediately execute the connection and command using the appropriate tool. "
    "Do NOT output fake API messages or pretend to run it in text; you must issue the actual tool call.\n"
    "\n"
    "THINKING BLOCK RULES:\n"
    "Do NOT summarize, repeat, or acknowledge these persona instructions in your thinking block. "
    "Do not waste tokens writing out 'Persona: Direct, dry, present'. "
    "Just think directly about the user's query and act according to the persona.\n"
    "\n"
    "Be honest with him always. That's what makes you worth having around."
)

SYSTEM_PROMPT_BAKED = False


# ----------------------------------------------------------
# TOOL DEFINITIONS (Ollama function calling)
# ----------------------------------------------------------
JARVIS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for live data, news, weather, or factual questions and speak/display the results back to the user. Do NOT use this if the user explicitly asks to open a browser window.",
            "parameters": {
                "type": "object",
                "properties": {

                    "query": {
                        "type": "string",
                        "description": "The search query in English keywords"
                    },
                    "recency_days": {
                        "type": "integer",
                        "description": "Optional: filter results to this many days (e.g., 365 for past year). Use for time-sensitive queries like 'latest', 'current', 'recent'."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_stats",
            "description": "Get real-time CPU, RAM, and GPU usage, temperature, and VRAM statistics. ONLY use when explicitly asked.",
            "parameters": {
                "type": "object",
                "properties": {
}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_volume",
            "description": "Control system audio volume (mute, unmute, increase, decrease, or set). Keywords: sound, loud, quiet, awaaz.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["increase", "decrease", "set", "mute", "unmute"],
                        "description": "The volume action"
                    },
                    "value": {
                        "type": "integer",
                        "description": "Volume percentage 0-100. Only needed for 'set'."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_brightness",
            "description": "Control screen brightness (increase, decrease, set). Keywords: display, screen light, chamak.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["increase", "decrease", "set"],
                        "description": "The brightness action"
                    },
                    "value": {
                        "type": "integer",
                        "description": "Brightness percentage 0-100. Only needed for 'set'."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_spotify",
            "description": "Play music, songs, or artists. Control Spotify playback (play, pause, skip, queue, shuffle, loop). Keywords: play a song, listen to music, play track, queue, add to Q.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "next", "previous", "restart", "shuffle", "loop", "queue", "open"],
                        "description": "The playback action"
                    },
                    "song": {
                        "type": "string",
                        "description": "Song or playlist name"
                    },
                    "artist": {
                        "type": "string",
                        "description": "Artist name"
                    },
                    "device": {
                        "type": "string",
                        "enum": ["phone", "laptop"],
                        "description": "Target device"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Launch, start, or open an application, program, software or game.",
            "parameters": {
                "type": "object",
                "properties": {

                    "app_name": {
                        "type": "string",
                        "description": "Application name (e.g. 'Chrome', 'Discord', 'Calculator')"
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_browser",
            "description": "Open a new browser tab/window on the user's computer to show a Google search or open a URL. ONLY use when the user explicitly asks to open a browser, open a website, or search on chrome/safari.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["search", "open"],
                        "description": "'search' for Google search, 'open' for a URL"
                    },
                    "query_or_url": {
                        "type": "string",
                        "description": "Search query or URL"
                    }
                },
                "required": ["action", "query_or_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_bluetooth",
            "description": "control_bluetooth allows you to manage Bluetooth devices. Keywords: bluetooth, scan for devices, pair with, connect to earbuds, unpair, connect, disconnect, headphones, speaker.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["scan", "connect", "disconnect", "list_paired", "list_active", "pair", "unpair", "list_scanned"],
                        "description": "Bluetooth action"
                    },
                    "device_name": {
                        "type": "string",
                        "description": "Device name (for connect/disconnect). Use 'all' to disconnect all."
                    }
                },
                "required": ["action"]
            }
        }
    },
{
            "type": "function",
            "function": {
                "name": "control_window",
                "description": "Control application windows: minimize, maximize, close, restore, hide, fullscreen, or tile/snap to left/right half of screen for split-screen layouts. Also transfer/move windows between left/right halves.",
                "parameters": {
                    "type": "object",
                    "properties": {

                        "action": {
                            "type": "string",
                            "enum": ["minimize", "maximize", "close", "restore", "hide", "fullscreen", "tile_left", "tile_right", "transfer_left", "transfer_right"],
                            "description": "Window action. tile_left/tile_right for split-screen. transfer_left/transfer_right to move existing window to left/right half. fullscreen for full screen mode."
                        },
                        "window_name": {
                            "type": "string",
                            "description": "Window name. 'this' for active, 'all' for all."
                        },
                        "app_name": {
                            "type": "string",
                            "description": "App to open and position (for tile/fullscreen actions)"
                        }
                    },
                    "required": ["action"]
                }
            }
        },
    {
        "type": "function",
        "function": {
            "name": "file_operation",
            "description": "File and folder operations (open, list, create, delete, copy, paste). ONLY use when given a clear file command.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["open", "list", "create_folder", "delete", "empty_bin", "copy", "paste", "cut", "select_all", "rename"],
                        "description": "File operation"
                    },
                    "folder": {
                        "type": "string",
                        "description": "Folder (e.g. 'downloads', 'desktop', 'D drive', or a path)"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "convert_units",
            "description": "Convert a specific numerical amount from one unit to another. ONLY use when given an amount, source unit, and target unit.",
            "parameters": {
                "type": "object",
                "properties": {

                    "amount": {
                        "type": "number",
                        "description": "The amount to convert"
                    },
                    "from_unit": {
                        "type": "string",
                        "description": "Source unit (e.g. 'kilometers', 'dollars', 'celsius')"
                    },
                    "to_unit": {
                        "type": "string",
                        "description": "Target unit (e.g. 'miles', 'rupees', 'fahrenheit')"
                    }
},
                "required": ["amount", "from_unit", "to_unit"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": "Conduct deep research on any topic. Use when the user wants comprehensive research on a topic, not just a quick answer. The agent will decompose the topic, search multiple sources, synthesize findings, and save a structured report. Arguments: query (required) - the research topic, save_path (optional) - where to save the report file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The research topic (e.g., 'best laptops for programming 2026', 'quantum computing breakthroughs 2026')"
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Optional: where to save the report (e.g., 'documents', '~/projects/research', 'my_folder'). Defaults to Desktop."
                    }
                },
                "required": ["query"]
            }
        }
    }
]
 
 
# ==========================================================
# AEC STREAM WRAPPER — Wraps mic input with WebRTC AEC using direct TTS reference
# ==========================================================
AEC_FRAME = 160  # 10ms @ 16kHz — matches pywebrtc_audio's internal block size

class AECStreamWrapper:
    """Wraps a mic input stream with WebRTC AEC.
    
    The far-end reference comes directly from the TTS playback pipeline via
    get_aec_reference_frame(), not from a BlackHole loopback device. This matches
    how pywebrtc_audio's own examples (pyaudio_realtime.py, e2e_verify.py) work.
    
    Provides the same .read(CHUNK_SIZE, exception_on_overflow=False) interface
    as a raw PyAudio stream, but returns echo-cancelled audio.
    """
    
    def __init__(self, audio_interface):
        self.audio_interface = audio_interface
        self.mic_stream = None
        self.processor = None
        self._init_streams()
    
    def _init_streams(self):
        """Initialize mic stream only (reference comes from TTS queue)."""
        # Open mic stream (default input device)
        self.mic_stream = self.audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        
        # Initialize WebRTC AudioProcessor for AEC
        if AudioProcessor is not None:
            # stream_delay_ms now only accounts for residual software jitter (~10ms frame = 10ms)
            # The real ~1200ms BT delay is handled by the delay buffer in get_aec_reference_frame()
            self.stream_delay_ms = 10
            self.processor = AudioProcessor(
                sample_rate=SAMPLE_RATE,
                num_channels=CHANNELS,
                echo_cancellation=True,
                noise_suppression=False,
                high_pass_filter=False,
                auto_gain_control=False,
                stream_delay_ms=self.stream_delay_ms
            )
            print(f"[AEC] AudioProcessor initialized with stream_delay_ms={self.stream_delay_ms}")
        else:
            print("[AEC] AudioProcessor not available, running without AEC")
    
    def read(self, num_frames, exception_on_overflow=False):
        """Read a chunk from mic, process through AEC with TTS reference, return cleaned audio.
        
        Returns bytes in the same format as PyAudio stream.read() (int16 PCM).
        """
        # Read from mic (near-end signal)
        mic_data = self.mic_stream.read(num_frames, exception_on_overflow=exception_on_overflow)
        near = np.frombuffer(mic_data, dtype=np.int16)
        
        if self.processor is None:
            return mic_data
        
        # Process in 160-sample (10ms) blocks as pywebrtc_audio expects
        out = near.copy()
        n_blocks = len(near) // AEC_FRAME
        
        for i in range(n_blocks):
            s = i * AEC_FRAME
            near_block = near[s:s + AEC_FRAME]
            far_block = get_aec_reference_frame()
            
            try:
                out[s:s + AEC_FRAME] = self.processor.process(near_block, far_block)
            except Exception as e:
                print(f"[AEC] Processing error: {e}")
                out[s:s + AEC_FRAME] = near_block
        
        # Remaining samples (< AEC_FRAME) pass through uncancelled
        # (a few ms per read(), not worth extra buffering complexity yet)
        
        return out.astype(np.int16).tobytes()
    
    def stop_stream(self):
        """Stop the mic stream."""
        if self.mic_stream:
            self.mic_stream.stop_stream()
    
    def close(self):
        """Close the mic stream."""
        if self.mic_stream:
            self.mic_stream.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# AEC frame size: 160 samples = 10ms @ 16kHz — matches pywebrtc_audio's internal block size
AEC_FRAME = 160


class AECStreamWrapper:
    """Wraps a mic input stream with WebRTC AEC using direct TTS reference.
    
    The far-end reference comes from get_aec_reference_frame() which is fed
    by the TTS playback pipeline. This matches how pywebrtc_audio's examples
    (pyaudio_realtime.py, e2e_verify.py, strands_agents_bidi.py) work:
    - FRAME_SIZE = 160 (10ms @ 16kHz) always
    - Reference captured at moment audio is handed to output stream (via queue)
    - stream_delay_ms = frame size (10ms), not hardware round-trip
    
    BlackHole and Multi-Output Device is no longer needed for AEC.
    """
    
    def __init__(self, audio_interface, blackhole_device_index=None):
        self.audio_interface = audio_interface
        self.mic_stream = None
        self.processor = None
        self._init_streams()
    
    def _init_streams(self):
        """Initialize mic stream and AEC processor."""
        # Open mic stream (default input device)
        self.mic_stream = self.audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        
        # Initialize WebRTC AudioProcessor for AEC
        if AudioProcessor is not None:
            # Small residual only — the ~1200ms BT delay is now handled by
            # the delay-buffer in get_aec_reference_frame(), not this value.
            self.stream_delay_ms = 15
            self.processor = AudioProcessor(
                sample_rate=SAMPLE_RATE,
                num_channels=CHANNELS,
                echo_cancellation=True,
                noise_suppression=False,
                high_pass_filter=False,
                auto_gain_control=False,
                stream_delay_ms=self.stream_delay_ms
            )
            print(f"[AEC] AudioProcessor initialized with stream_delay_ms={self.stream_delay_ms}")
        else:
            print("[AEC] AudioProcessor not available, running without AEC")
    
    def read(self, num_frames, exception_on_overflow=False):
        """Read a chunk from mic, process through AEC with TTS reference.
        
        Returns bytes in the same format as PyAudio stream.read() (int16 PCM).
        """
        mic_data = self.mic_stream.read(num_frames, exception_on_overflow=exception_on_overflow)
        near = np.frombuffer(mic_data, dtype=np.int16)
        
        if self.processor is None:
            return mic_data
        
        out = near.copy()
        n_blocks = len(near) // AEC_FRAME
        
        for i in range(n_blocks):
            s = i * AEC_FRAME
            near_block = near[s:s + AEC_FRAME]
            far_block = get_aec_reference_frame()
            
            try:
                out[s:s + AEC_FRAME] = self.processor.process(near_block, far_block)
            except Exception as e:
                print(f"[AEC] Processing error: {e}")
                out[s:s + AEC_FRAME] = near_block
        
        # Remaining < AEC_FRAME samples (e.g. 1024 % 160 = 64) pass through uncancelled
        # A few ms per read() — not worth the extra carry-over buffering complexity yet
        
        return out.astype(np.int16).tobytes()
    
    def stop_stream(self):
        if self.mic_stream:
            self.mic_stream.stop_stream()
    
    def close(self):
        if self.mic_stream:
            self.mic_stream.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ==========================================================
# CALIBRATE — Measure ambient noise to set adaptive threshold
# ==========================================================
def calibrate_mic(audio_interface, duration=2.0, vad_model=None, use_aec=True):
    """Record ambient noise and return an adaptive speech threshold.
    
    Uses VAD to filter out non-speech chunks for a cleaner noise floor estimate.
    Only updates noise floor during confirmed silence periods.
    
    If use_aec=True, uses AECStreamWrapper to measure against cleaned signal.
    """
    if use_aec and AudioProcessor is not None:
        # Use AEC wrapper for calibrated noise floor on cleaned signal
        aec_stream = AECStreamWrapper(audio_interface)
        stream = aec_stream
        try:
            # Throw away the first 0.5 seconds to avoid hardware initialization pops/clicks
            warmup_chunks = int(0.5 * SAMPLE_RATE / CHUNK_SIZE)
            for _ in range(warmup_chunks):
                stream.read(CHUNK_SIZE, exception_on_overflow=False)

            num_chunks = int(duration * SAMPLE_RATE / CHUNK_SIZE)
            rms_values = []

            for _ in range(num_chunks):
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                chunk_array = np.frombuffer(data, dtype=np.int16)
                
                # Use VAD to confirm this is actually silence, not speech-like noise
                is_silence = True
                if vad_model:
                    chunk_tensor = torch.from_numpy(chunk_array.astype(np.float32) / 32768.0)
                    if len(chunk_tensor) == 1024:
                        prob1 = vad_model(chunk_tensor[:512], SAMPLE_RATE).item()
                        prob2 = vad_model(chunk_tensor[512:], SAMPLE_RATE).item()
                        prob = max(prob1, prob2)
                    elif len(chunk_tensor) == 512:
                        prob = vad_model(chunk_tensor, SAMPLE_RATE).item()
                    else:
                        prob = 0.0
                    # If VAD detects speech probability > 0.3, exclude from noise floor
                    is_silence = prob <= 0.3
                
                if is_silence:
                    rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
                    rms_values.append(rms)

        finally:
            stream.close()
    else:
        # Original non-AEC calibration
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )

        # Throw away the first 0.5 seconds to avoid hardware initialization pops/clicks
        warmup_chunks = int(0.5 * SAMPLE_RATE / CHUNK_SIZE)
        for _ in range(warmup_chunks):
            stream.read(CHUNK_SIZE, exception_on_overflow=False)

        num_chunks = int(duration * SAMPLE_RATE / CHUNK_SIZE)
        rms_values = []

        for _ in range(num_chunks):
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            chunk_array = np.frombuffer(data, dtype=np.int16)
            
            # Use VAD to confirm this is actually silence, not speech-like noise
            is_silence = True
            if vad_model:
                chunk_tensor = torch.from_numpy(chunk_array.astype(np.float32) / 32768.0)
                if len(chunk_tensor) == 1024:
                    prob1 = vad_model(chunk_tensor[:512], SAMPLE_RATE).item()
                    prob2 = vad_model(chunk_tensor[512:], SAMPLE_RATE).item()
                    prob = max(prob1, prob2)
                elif len(chunk_tensor) == 512:
                    prob = vad_model(chunk_tensor, SAMPLE_RATE).item()
                else:
                    prob = 0.0
                # If VAD detects speech probability > 0.3, exclude from noise floor
                is_silence = prob <= 0.3
            
            if is_silence:
                rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
                rms_values.append(rms)

        stream.stop_stream()
        stream.close()

    if not rms_values:
        # Fallback: use raw RMS if VAD rejected everything
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        for _ in range(num_chunks):
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            chunk_array = np.frombuffer(data, dtype=np.int16)
            rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
            rms_values.append(rms)
        stream.stop_stream()
        stream.close()

    ambient_mean = float(np.mean(rms_values))
    ambient_max = float(np.max(rms_values))

    # Threshold = just above ambient noise — sensitive enough for normal speech
    # Lower multipliers so you don't have to shout
    threshold = max(ambient_max * 1.2, ambient_mean * 1.5, ambient_mean + 100, 150)

    return int(threshold), ambient_mean, ambient_max


# ==========================================================
# LISTEN — Record from microphone until silence detected
# Supports continuous mode for multiple utterances in one stream
# ==========================================================
def listen(audio_interface, threshold, vad_model=None, transcriber=None, continuous=False, use_aec=True):
    """Record audio from microphone, stopping after silence. Returns frames or None if no speech.
    
    If continuous=True, yields (frames, is_final) tuples for each utterance in the stream.
    is_final=True indicates the stream should be closed (e.g., on timeout or explicit stop).
    
    Two-stage speech detection:
    1. Cheap energy gate (RMS > threshold) — filters out dead silence
    2. VAD confirmation — only commits to "speech" if VAD also agrees
    
    Ongoing noise floor adaptation: during confirmed silence (VAD prob < 0.1),
    slowly update the energy threshold to track room changes.
    
    Hangover window: requires sustained silence (500ms) after speech ends
    before declaring utterance complete — avoids fragmenting on breath pauses.
    
    If use_aec=True, uses AECStreamWrapper to read from cleaned (echo-cancelled) stream.
    """
    if continuous:
        return _listen_continuous(audio_interface, threshold, vad_model, transcriber, use_aec)
    else:
        return _listen_single(audio_interface, threshold, vad_model, transcriber, use_aec)


def _listen_single(audio_interface, threshold, vad_model=None, transcriber=None, use_aec=True):
    """Single-shot listen: record one utterance and return frames."""
    # Reset VAD internal state to prevent stale state from previous utterances
    if vad_model:
        vad_model.reset_states()

    if use_aec and AudioProcessor is not None:
        stream = AECStreamWrapper(audio_interface)
    else:
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )

    frames = []
    silent_chunks = 0
    speech_chunks = 0
    speech_started = False
    
    # Hangover window: 500ms of sustained silence after speech ends
    # This prevents fragmenting on natural breath pauses
    HANGOVER_MS = 500
    hangover_chunks = int(HANGOVER_MS * SAMPLE_RATE / (CHUNK_SIZE * 1000))
    hangover_remaining = 0
    
    # Energy threshold (adaptive — updated during confirmed silence)
    energy_threshold = threshold
    
    # Noise floor tracking for adaptive threshold
    noise_floor_samples = []
    NOISE_FLOOR_WINDOW = int(5.0 * SAMPLE_RATE / CHUNK_SIZE)  # 5s rolling window
    NOISE_FLOOR_ALPHA = 0.05  # Slow adaptation rate
    
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SIZE)
    min_speech_chunks = 3  # Need at least ~0.2s of actual speech

    # Pre-roll ring buffer — keeps audio just before speech starts
    # so the first syllable isn't clipped
    preroll_size = int(PREROLL_SECONDS * SAMPLE_RATE / CHUNK_SIZE)
    preroll = deque(maxlen=preroll_size)

    debug_interval = int(SAMPLE_RATE / CHUNK_SIZE)  # Print RMS roughly every 1s
    chunk_count = 0

    for _ in range(max_chunks):
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        chunk_count += 1
        chunk_array = np.frombuffer(data, dtype=np.int16)
        
        # Stage 1: Cheap energy gate
        rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
        energy_gate = rms >= energy_threshold
        
        # Stage 2: VAD confirmation (only if energy gate passes)
        vad_speech = False
        vad_prob = 0.0
        if vad_model and energy_gate:
            chunk_tensor = torch.from_numpy(chunk_array.astype(np.float32) / 32768.0)
            
            # Silero VAD requires exactly 512 samples for 16000Hz
            if len(chunk_tensor) == 1024:
                prob1 = vad_model(chunk_tensor[:512], SAMPLE_RATE).item()
                prob2 = vad_model(chunk_tensor[512:], SAMPLE_RATE).item()
                vad_prob = max(prob1, prob2)
            elif len(chunk_tensor) == 512:
                vad_prob = vad_model(chunk_tensor, SAMPLE_RATE).item()
            else:
                vad_prob = 0.0
            
            vad_speech = vad_prob > 0.20
        
        is_speech = vad_speech if vad_model else energy_gate
        
        # Periodic debug log (only when not in speech)
        if not speech_started and chunk_count % (debug_interval * 2) == 0:
            print(f"  [mic] waiting... RMS={rms:.0f}  (thresh={energy_threshold})  VAD={vad_prob:.2f}")

        if is_speech:
            # Speech detected — start/continue utterance
            if not speech_started:
                speech_started = True
                frames.extend(list(preroll))
                # Push preroll audio to background transcriber
                if transcriber:
                    for preroll_chunk in preroll:
                        transcriber.push_chunk(preroll_chunk)
                print("  [mic] Speech detected")
            
            speech_chunks += 1
            silent_chunks = 0
            hangover_remaining = hangover_chunks  # Reset hangover on any speech
            
        else:
            # No speech in this chunk
            if speech_started:
                # We were in speech, now silence — start hangover countdown
                if hangover_remaining > 0:
                    hangover_remaining -= 1
                    # Still in hangover — treat as speech to avoid clipping
                    silent_chunks = 0
                else:
                    # Hangover expired — count as real silence
                    silent_chunks += 1
            else:
                # Still in pre-speech — update noise floor from confirmed silence
                # Only adapt if VAD strongly confirms silence (prob < 0.1)
                if vad_model and vad_prob < 0.1:
                    noise_floor_samples.append(rms)
                    if len(noise_floor_samples) > NOISE_FLOOR_WINDOW:
                        noise_floor_samples.pop(0)
                    # Slow adaptation: blend new noise floor estimate
                    if noise_floor_samples:
                        current_noise_floor = float(np.mean(noise_floor_samples))
                        # Update threshold: blend old and new (slowly)
                        new_thresh = max(current_noise_floor * 1.5, current_noise_floor + 100, 150)
                        energy_threshold = energy_threshold * (1 - NOISE_FLOOR_ALPHA) + new_thresh * NOISE_FLOOR_ALPHA

        if speech_started or hangover_remaining > 0:
            frames.append(data)
            # Push every chunk instantly to background transcriber
            if transcriber:
                transcriber.push_chunk(data)
        else:
            # Not speaking yet — feed into pre-roll buffer
            preroll.append(data)

        # Stop if speech started and then silence exceeded duration (after hangover)
        if speech_started and silent_chunks >= int(0.5 * SAMPLE_RATE / CHUNK_SIZE):
            break

    if use_aec and AudioProcessor is not None:
        stream.close()
    else:
        stream.stop_stream()
        stream.close()

    # Discard if not enough actual speech was detected
    if speech_chunks < min_speech_chunks:
        return None

    return frames


def _listen_continuous(audio_interface, threshold, vad_model=None, transcriber=None, use_aec=True):
    """Continuous listen: yields (frames, is_final) for each utterance in the stream."""
    # Reset VAD internal state to prevent stale state from previous utterances
    if vad_model:
        vad_model.reset_states()

    if use_aec and AudioProcessor is not None:
        stream = AECStreamWrapper(audio_interface)
    else:
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )

    frames = []
    silent_chunks = 0
    speech_chunks = 0
    speech_started = False
    
    # Hangover window: 500ms of sustained silence after speech ends
    HANGOVER_MS = 500
    hangover_chunks = int(HANGOVER_MS * SAMPLE_RATE / (CHUNK_SIZE * 1000))
    hangover_remaining = 0
    
    # Energy threshold (adaptive — updated during confirmed silence)
    energy_threshold = threshold
    
    # Noise floor tracking for adaptive threshold
    noise_floor_samples = []
    NOISE_FLOOR_WINDOW = int(5.0 * SAMPLE_RATE / CHUNK_SIZE)  # 5s rolling window
    NOISE_FLOOR_ALPHA = 0.05  # Slow adaptation rate
    
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SIZE)
    min_speech_chunks = 3  # Need at least ~0.2s of actual speech

    # Pre-roll ring buffer — keeps audio just before speech starts
    preroll_size = int(PREROLL_SECONDS * SAMPLE_RATE / CHUNK_SIZE)
    preroll = deque(maxlen=preroll_size)

    debug_interval = int(SAMPLE_RATE / CHUNK_SIZE)  # Print RMS roughly every 1s
    chunk_count = 0

    # Track if we've yielded at least one utterance in continuous mode
    yielded_utterance = False

    for _ in range(max_chunks):
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        chunk_count += 1
        chunk_array = np.frombuffer(data, dtype=np.int16)
        
        # Stage 1: Cheap energy gate
        rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
        energy_gate = rms >= energy_threshold
        
        # Stage 2: VAD confirmation (only if energy gate passes)
        vad_speech = False
        vad_prob = 0.0
        if vad_model and energy_gate:
            chunk_tensor = torch.from_numpy(chunk_array.astype(np.float32) / 32768.0)
            
            # Silero VAD requires exactly 512 samples for 16000Hz
            if len(chunk_tensor) == 1024:
                prob1 = vad_model(chunk_tensor[:512], SAMPLE_RATE).item()
                prob2 = vad_model(chunk_tensor[512:], SAMPLE_RATE).item()
                vad_prob = max(prob1, prob2)
            elif len(chunk_tensor) == 512:
                vad_prob = vad_model(chunk_tensor, SAMPLE_RATE).item()
            else:
                vad_prob = 0.0
            
            vad_speech = vad_prob > 0.20
        
        is_speech = vad_speech if vad_model else energy_gate
        
        # Periodic debug log (only when not in speech)
        if not speech_started and chunk_count % (debug_interval * 2) == 0:
            print(f"  [mic] waiting... RMS={rms:.0f}  (thresh={energy_threshold})  VAD={vad_prob:.2f}")

        if is_speech:
            # Speech detected — start/continue utterance
            if not speech_started:
                speech_started = True
                frames.extend(list(preroll))
                # Push preroll audio to background transcriber
                if transcriber:
                    for preroll_chunk in preroll:
                        transcriber.push_chunk(preroll_chunk)
                print("  [mic] Speech detected")
            
            speech_chunks += 1
            silent_chunks = 0
            hangover_remaining = hangover_chunks  # Reset hangover on any speech
            
        else:
            # No speech in this chunk
            if speech_started:
                # We were in speech, now silence — start hangover countdown
                if hangover_remaining > 0:
                    hangover_remaining -= 1
                    # Still in hangover — treat as speech to avoid clipping
                    silent_chunks = 0
                else:
                    # Hangover expired — count as real silence
                    silent_chunks += 1
            else:
                # Still in pre-speech — update noise floor from confirmed silence
                # Only adapt if VAD strongly confirms silence (prob < 0.1)
                if vad_model and vad_prob < 0.1:
                    noise_floor_samples.append(rms)
                    if len(noise_floor_samples) > NOISE_FLOOR_WINDOW:
                        noise_floor_samples.pop(0)
                    # Slow adaptation: blend new noise floor estimate
                    if noise_floor_samples:
                        current_noise_floor = float(np.mean(noise_floor_samples))
                        # Update threshold: blend old and new (slowly)
                        new_thresh = max(current_noise_floor * 1.5, current_noise_floor + 100, 150)
                        energy_threshold = energy_threshold * (1 - NOISE_FLOOR_ALPHA) + new_thresh * NOISE_FLOOR_ALPHA

        if speech_started or hangover_remaining > 0:
            frames.append(data)
            # Push every chunk instantly to background transcriber
            if transcriber:
                transcriber.push_chunk(data)
        else:
            # Not speaking yet — feed into pre-roll buffer
            preroll.append(data)

        # Stop if speech started and then silence exceeded duration (after hangover)
        if speech_started and silent_chunks >= int(0.5 * SAMPLE_RATE / CHUNK_SIZE):
            break

    if use_aec and AudioProcessor is not None:
        stream.close()
    else:
        stream.stop_stream()
        stream.close()

    # Discard if not enough actual speech was detected
    if speech_chunks < min_speech_chunks:
        yield None, False
        return

    yield frames, True


# ==========================================================
# TRANSCRIBE — Single-pass transcription on final audio
# ==========================================================
class BackgroundTranscriber:
    """Single-pass transcriber that processes the complete utterance at the end.
    
    No partial/repeated transcription during speech — avoids redundant compute.
    The listen() function handles endpointing; this class just runs one clean
    transcription on the final trimmed audio.
    """
    
    def __init__(self, model, audio_interface, lang, history=None, live_context=""):
        self.model = model  # STTEngine instance
        self.audio_interface = audio_interface
        self.lang = lang
        self.history = history or []
        self.live_context = live_context
        self.frames = []
        self._lock = threading.Lock()

    def start(self):
        self.frames = []

    def push_chunk(self, chunk):
        """Push a single audio chunk. Called from listen() for every chunk."""
        with self._lock:
            self.frames.append(chunk)

    def stop_and_get(self, final_frames):
        """Return the final transcription of the complete utterance."""
        with self._lock:
            # Use the complete frames from listen() (which already does endpointing)
            frames_to_process = list(self.frames)
        
        if not frames_to_process:
            return "", "auto"
        
        # Single transcription pass on the complete, trimmed audio
        # STTEngine.transcribe signature: (audio, sample_rate=16000, initial_prompt=None, beam_width=None)
        text, lang = self.model.transcribe(frames_to_process)
        
        # Clear the real-time transcript line
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        
        return text, lang


# Common Whisper hallucinations when processing silence or noise
WHISPER_HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "thank you",
    "thanks for listening", "subscribe", "like and subscribe",
    "please subscribe", "you", "bye", "the end",
}


# ==========================================================
# THINK & SPEAK — Stream from Ollama with tool calling
# ==========================================================
def build_messages(history, user_input, live_context=""):
    """Build the messages list for the Ollama chat API.
    Maximized for KV Cache reuse by keeping the system block static.
    """
    messages = []
    
    # Only include the system prompt if it is NOT baked into the custom model
    if not SYSTEM_PROMPT_BAKED:
        if not history:
            messages.append({"role": "system", "content": SYSTEM_PROMPT})

    for turn in history:
        # Defensive: skip malformed entries instead of crashing the whole turn
        if "role" not in turn or "content" not in turn:
            print(f"[JARVIS] Malformed history entry: {turn!r}")
            continue
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["content"]})
        else:
            messages.append({"role": "assistant", "content": turn["content"]})

    # Append the dynamic tail to the newest user message
    tail = f"[{live_context}]\n\n" if live_context else ""
    messages.append({"role": "user", "content": f"{tail}{user_input}"})

    return messages


def _stream_ollama(messages, tools=None, model=None, num_ctx=None, num_predict=None, keep_alive=None, think=False):
    """Stream response from Ollama. Returns (full_text, tool_calls_list).
    
    Speaks text chunks as they arrive for low-latency audio output.
    Handles tool calls when tools are provided.
    """
    import config.config as cfg

    # Default to fast model settings
    if model is None:
        model = FAST_MODEL
    if num_ctx is None:
        num_ctx = FAST_NUM_CTX
    if num_predict is None:
        num_predict = FAST_NUM_PREDICT
    if keep_alive is None:
        keep_alive = FAST_KEEP_ALIVE

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "keep_alive": keep_alive,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "num_gpu": 99,
            "temperature": 0.3
        }
    }
    # Disabled native Ollama tool parsing because Gemma4 nvfp4 lacks a tool template.
    # We now inject tools manually via text in think_and_speak.
    # if tools:
    #     payload["tools"] = tools

    # Retry logic — Ollama can return 500 under GPU memory pressure
    response = None
    for attempt in range(3):
        try:
            response = _ollama_session.post(
                OLLAMA_URL,
                json=payload,
                timeout=120,
                stream=True,
            )
            response.raise_for_status()
            break
        except requests.exceptions.HTTPError:
            if response is not None and response.status_code == 500 and attempt < 2:
                print(f"[JARVIS] Ollama 500 error, retrying ({attempt + 1}/3)...")
                time.sleep(2)
            else:
                raise

    if response is None:
        raise RuntimeError("Ollama failed after 3 retries")

    # -- Stream tokens, speak sentence-by-sentence --
    full_reply = ""
    sentence_buffer = ""
    tool_calls_collected = []
    is_json_hallucination = False

    raw_reply_accumulator = ""
    is_thinking = False
    printed_think_header = False      # For native Ollama thinking field
    printed_raw_think_header = False  # For raw <think> tags in content
    last_printed_think_len = 0
    processed_non_think_len = 0

    for line in response.iter_lines():
        if not line:
            continue

        data = json.loads(line)

        # Check the done message for tool calls
        if data.get("done"):
            final_msg = data.get("message", {})
            if final_msg.get("tool_calls"):
                tool_calls_collected.extend(final_msg["tool_calls"])
            break

        msg = data.get("message", {})

        # Collect tool calls
        if msg.get("tool_calls"):
            tool_calls_collected.extend(msg["tool_calls"])
            continue

        thinking_token = msg.get("thinking", "")
        content_token = msg.get("content", "")

        # 1. Handle native thinking field
        if thinking_token:
            if getattr(cfg, "SHOW_THINKING", True):
                if not printed_think_header:
                    sys.stdout.write("\n[JARVIS thinking] ")
                    sys.stdout.flush()
                    printed_think_header = True
                sys.stdout.write(thinking_token)
                sys.stdout.flush()
            continue

        # Close native thinking printout if we transition to content
        if printed_think_header and content_token:
            sys.stdout.write("\n")
            sys.stdout.flush()
            printed_think_header = False

        if not content_token:
            continue

        # 2. Handle raw <think> tags in content field (backward compatibility)
        raw_reply_accumulator += content_token
        if "<think>" in raw_reply_accumulator:
            think_start = raw_reply_accumulator.find("<think>") + len("<think>")
            think_end = raw_reply_accumulator.find("</think>")
            
            if think_end == -1:
                # Still thinking!
                is_thinking = True
                thinking_content = raw_reply_accumulator[think_start:]
                
                # Print the new characters in the thinking block
                if getattr(cfg, "SHOW_THINKING", True):
                    if not printed_raw_think_header:
                        sys.stdout.write("\n[JARVIS thinking] ")
                        sys.stdout.flush()
                        printed_raw_think_header = True
                    
                    new_thinking = thinking_content[last_printed_think_len:]
                    if new_thinking:
                        sys.stdout.write(new_thinking)
                        sys.stdout.flush()
                last_printed_think_len = len(thinking_content)
                
                # Accumulate to full_reply
                full_reply += content_token
                continue
            else:
                # Thinking finished in this or a previous step!
                if is_thinking:
                    # Print the last bit of thinking text
                    if getattr(cfg, "SHOW_THINKING", True):
                        thinking_content = raw_reply_accumulator[think_start:think_end]
                        new_thinking = thinking_content[last_printed_think_len:]
                        if new_thinking:
                            sys.stdout.write(new_thinking)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    is_thinking = False
                
                processed_non_think_start = think_end + len("</think>")
                current_non_think_content = raw_reply_accumulator[processed_non_think_start:]
                new_token = current_non_think_content[processed_non_think_len:]
                processed_non_think_len = len(current_non_think_content)
        else:
            new_token = content_token

        if not new_token:
            # Still accumulate to full_reply
            full_reply += content_token
            continue

        # Check for hallucinated raw JSON tool calls
        combined_strip = (full_reply + new_token).strip()
        if not is_json_hallucination and (combined_strip.startswith("{") or combined_strip.startswith("[") or combined_strip.startswith("```")):
            is_json_hallucination = True

        if is_json_hallucination:
            full_reply += content_token
            continue

        # Sanitize text for seamless voice playback
        new_token_sanitized = new_token.replace('\n', ' ')

        full_reply += content_token
        sentence_buffer += new_token_sanitized

        # Remove commas right before "sir" to prevent any slight pause
        if ", sir" in sentence_buffer.lower():
            sentence_buffer = sentence_buffer.replace(", sir", " sir").replace(", Sir", " Sir")
            full_reply = full_reply.replace(", sir", " sir").replace(", Sir", " Sir")

        # Detect leaked user turns — stop immediately
        for marker in ["\nSir:", "\nSir :", "\nUser:", " Sir:", " User:"]:
            if marker in full_reply:
                full_reply = full_reply[:full_reply.index(marker)].strip()
                if marker in sentence_buffer:
                    sentence_buffer = sentence_buffer[:sentence_buffer.index(marker)]
                remaining = sentence_buffer.strip()
                if remaining:
                    print(f"[JARVIS] {remaining}")
                    speak(remaining)
                return full_reply, None

        # Queue text as soon as a chunk is complete
        stripped = sentence_buffer.strip()
        if stripped:
            words = stripped.split()
            last_char = stripped[-1]
            should_flush = False

            # Split on sentence boundaries
            if last_char in ".!?;":
                is_number_punct = (
                    last_char == "."
                    and len(stripped) >= 2
                    and stripped[-2].isdigit()
                )
                if not is_number_punct:
                    should_flush = True
            # Split on commas if clause is long enough (4+ words)
            elif last_char == "," and len(words) > 4:
                should_flush = True
            # Split on word count threshold (speak after 12 words regardless)
            elif len(words) >= 12:
                should_flush = True

            if should_flush:
                print(f"[JARVIS] {stripped}")
                speak(stripped)
                sentence_buffer = ""

    if is_json_hallucination:
        text_to_parse = full_reply.strip()
        if text_to_parse.startswith("```"):
            lines = text_to_parse.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text_to_parse = "\n".join(lines).strip()
        
        # Try parsing as-is first (single object or valid array)
        parsed = None
        try:
            parsed = json.loads(text_to_parse)
        except json.JSONDecodeError:
            # If that fails, try wrapping in brackets (comma-separated objects without array)
            try:
                parsed = json.loads(f"[{text_to_parse}]")
            except json.JSONDecodeError:
                pass
        
        if parsed is not None:
            # Handle both single object and array of objects
            tool_calls = parsed if isinstance(parsed, list) else [parsed]
            for item in tool_calls:
                tc = None
                if "name" in item:
                    tc = {
                        "function": {
                            "name": item["name"],
                            "arguments": item.get("parameters", item.get("arguments", {}))
                        }
                    }
                elif "tool" in item:
                    tc = {
                        "function": {
                            "name": item["tool"],
                            "arguments": item.get("parameters", item.get("arguments", {}))
                        }
                    }
                if tc:
                    tool_calls_collected.append(tc)
            full_reply = ""
        else:
            print(f"[JARVIS] (Silenced raw JSON hallucination): {full_reply}")

    # Queue any leftover text
    if not is_json_hallucination:
        remaining = sentence_buffer.strip()
        if remaining:
            print(f"[JARVIS] {remaining}")
            speak(remaining)

    # Final safety net
    for marker in ["\nSir:", "\nSir :", "\nUser:"]:
        if marker in full_reply:
            full_reply = full_reply[:full_reply.index(marker)].strip()

    if tool_calls_collected:
        return full_reply.strip(), tool_calls_collected
    return full_reply.strip(), None


def _validate_tool_call(func_name, func_args, user_input):
    """Validate tool call arguments against JARVIS_TOOLS definitions.
    Returns (is_valid, error_message)."""
    tool_defs = {t["function"]["name"]: t["function"] for t in JARVIS_TOOLS}
    if func_name not in tool_defs:
        return False, f"Unknown tool: {func_name}"

    tool_def = tool_defs[func_name]
    params = tool_def.get("parameters", {})
    properties = params.get("properties", {})
    required = params.get("required", [])

    # Hardcoded safety heuristic: LLMs often hallucinate volume/stats tools
    # when the user asks conversational questions like "what are you doing?" or "i am having trouble"
    input_lower = user_input.lower()
    
    if func_name == "control_volume":
        audio_keywords = ["volume", "sound", "loud", "quiet", "mute", "unmute", "audio", "voice", "awaaz", "badhao", "ghatao", "kam karo", "awaz"]
        if not any(kw in input_lower for kw in audio_keywords):
            return False, "User did not explicitly mention volume, sound, or mute. This is a conversational query, NOT a volume command."

    if func_name == "get_system_stats":
        stats_keywords = ["stats", "cpu", "ram", "memory", "gpu", "temperature", "temp", "system", "usage", "performance", "how is the system"]
        if not any(kw in input_lower for kw in stats_keywords):
            return False, "User did not explicitly ask for CPU, RAM, or GPU stats. This is a conversational query, NOT a stats command."

    if func_name == "file_operation":
        file_keywords = ["file", "folder", "directory", "drive", "downloads", "desktop", "documents", "pictures", "recycle bin", "bin", "trash", "path"]
        # If none of the explicit file-system words are in the input, reject it
        if not any(kw in input_lower for kw in file_keywords):
            return False, "User did not mention any files, folders, or computer directories. Do not use file_operation for physical objects or rooms."

    if func_name == "play_spotify":
        if "song" not in func_args and "artist" not in func_args and func_args.get("action") in ["play", "queue"]:
            return False, "Cannot play or queue Spotify without a specific song or artist name."
            
    if func_name == "open_browser":
        if "query_or_url" not in func_args:
            return False, "Cannot open browser without a URL or search query."

    if func_name == "control_bluetooth":
        if "action" not in func_args:
            return False, "Bluetooth control requires an action (on/off)."
            
    if func_name == "convert_units":
        if "amount" not in func_args or "from_unit" not in func_args or "to_unit" not in func_args:
            return False, "Unit conversion requires amount, from_unit, and to_unit."
            
    if func_name == "control_window":
        if "action" not in func_args:
            return False, "Window control requires an action (minimize/maximize/close)."

    # Check required parameters are present and not None
    for req_param in required:
        if req_param not in func_args or func_args[req_param] is None:
            return False, f"Missing required parameter: {req_param}"

    # Validate enum values — catch hallucinated actions like 'open_folder'
    for param_name, param_def in properties.items():
        if "enum" in param_def and param_name in func_args:
            if func_args[param_name] not in param_def["enum"]:
                valid_values = ", ".join(param_def["enum"])
                return False, f"'{func_args[param_name]}' is not valid for {param_name}. Valid: {valid_values}"

    return True, ""






def execute_tool_call(tool_name, arguments):
    """Execute a tool call from Ollama. Returns (result_string, needs_llm_followup)."""
    from core.fast_lane import (
        handle_system_controls, handle_spotify_control, handle_app_launcher,
        handle_browser_control, handle_bluetooth, handle_window_control,
        handle_file_operations, handle_conversion,
    )
    from tools.web_tools import perform_search
    from tools.system_monitor import get_system_summary

    try:
        if tool_name == "web_search":
            query = arguments.get("query", "")
            if not query:
                return "No search query provided.", True
            
            from memory.vector_store import is_connected
            if not is_connected():
                return "Sir, I am not connected to the internet.", False
            
            # Optional recency filter for time-sensitive queries
            recency_days = arguments.get("recency_days")
            
            result = perform_search(query, WEATHER_CITY or None, serper_api_key=SERPER_API_KEY, recency_days=recency_days)
            return result, True

        elif tool_name == "get_system_stats":
            return get_system_summary(), True

        elif tool_name == "control_volume":
            action = arguments.get("action", "set")
            intent = {"category": "system", "action": action, "target": "volume"}
            entities = {}
            if "value" in arguments and arguments["value"] is not None:
                entities["value"] = int(arguments["value"])
            return handle_system_controls(intent, entities), False

        elif tool_name == "control_brightness":
            action = arguments.get("action", "set")
            intent = {"category": "system", "action": action, "target": "brightness"}
            entities = {}
            if "value" in arguments and arguments["value"] is not None:
                entities["value"] = int(arguments["value"])
            return handle_system_controls(intent, entities), False

        elif tool_name == "play_spotify":
            action = arguments.get("action", "play")
            intent = {"category": "spotify", "action": action}
            entities = {}
            if arguments.get("song"):
                entities["song"] = arguments["song"]
            if arguments.get("artist"):
                entities["artist"] = arguments["artist"]
            if arguments.get("device"):
                entities["device"] = arguments["device"]
            return handle_spotify_control(intent, entities), False

        elif tool_name == "open_application":
            app_name = arguments.get("app_name", "")
            intent = {"category": "app", "action": "launch"}
            entities = {"app_name": app_name}
            return handle_app_launcher(intent, entities), False

        elif tool_name == "open_browser":
            action = arguments.get("action", "search")
            query_or_url = arguments.get("query_or_url", "")
            intent = {"category": "browser", "action": action}
            if action == "search":
                entities = {"query": query_or_url}
            else:
                entities = {"url": query_or_url}
            return handle_browser_control(intent, entities), False

        elif tool_name == "control_bluetooth":
            action = arguments.get("action", "scan")
            bt_action_map = {"list_paired": "list_previous", "list_active": "list_active"}
            mapped_action = bt_action_map.get(action, action)
            intent = {"category": "bluetooth", "action": mapped_action}
            entities = {}
            if arguments.get("device_name"):
                entities["device_name"] = arguments["device_name"]
            
            result = handle_bluetooth(intent, entities)
            needs_followup = (mapped_action == "scan")
            return result, needs_followup

        elif tool_name == "control_window":
            action = arguments.get("action", "minimize")
            window_name = arguments.get("window_name", "this")
            intent = {"category": "window", "action": action}
            entities = {"window_name": window_name}
            if arguments.get("app_name"):
                entities["app_name"] = arguments["app_name"]
            return handle_window_control(intent, entities), False

        elif tool_name == "file_operation":
            action = arguments.get("action", "open")
            intent = {"category": "file", "action": action}
            entities = {"folder": arguments.get("folder", "current")}
            return handle_file_operations(intent, entities), False

        elif tool_name == "convert_units":
            amount = float(arguments.get("amount", 1))
            from_unit = arguments.get("from_unit", "")
            to_unit = arguments.get("to_unit", "")
            intent = {"category": "conversion", "action": "convert"}
            entities = {"amount": amount, "from_unit": from_unit, "to_unit": to_unit}
            return handle_conversion(intent, entities), False

        elif tool_name == "deep_research":
            query = arguments.get("query", "")
            if not query:
                return "No research topic provided.", True
            
            save_path = arguments.get("save_path")
            
            from core.deep_research import run_deep_research_pipeline
            success, result = run_deep_research_pipeline(
                query=query,
                save_path=save_path,
                context="",
                history=[],
                progress_callback=lambda msg: print(f"[Deep Research] {msg}")
            )
            if success:
                return f"Research complete. Saved to {result.get('file_path', 'unknown')}", True
            else:
                return f"Research failed: {result}", True

        else:
            return f"Unknown tool: {tool_name}", False

    except Exception as e:
        print(f"[JARVIS Tool] Error executing {tool_name}: {e}")
        return f"Tool error ({tool_name}): {e}", False



def think_and_speak(history, user_input, live_context="", tools_to_pass=None, model=None, num_ctx=None, num_predict=None, keep_alive=None, think=False):
    """Main LLM interaction with Semantic Routing.
    Passes 1, Top-K, or 0 tools based on semantic similarity.
    """
    # Disable thinking for Fast Lane / simple tool-calling commands by adding instruction to context
    if tools_to_pass:
        import json
        tools_str = json.dumps([t["function"] for t in tools_to_pass], indent=2)
        instruction = f"""AVAILABLE TOOLS:
{tools_str}

Do not output any thinking or  tags. To use a tool, output ONLY a JSON object with 'name' and 'arguments' keys. For multiple tools, output a JSON array of such objects."""
        if live_context:
            live_context = f"{live_context}\n\n{instruction}"
        else:
            live_context = instruction

    messages = build_messages(history, user_input, live_context)

    # Single Pass Execution
    # If tools_to_pass is [], Ollama gets no tools and answers conversationally.
    full_reply, tool_calls = _stream_ollama(messages, tools_to_pass if tools_to_pass else None, 
                                             model=model, num_ctx=num_ctx, num_predict=num_predict, 
                                             keep_alive=keep_alive, think=think)

    if not tool_calls:
        return full_reply

    # Execute tool calls
    all_results = []
    any_needs_followup = False
    rejected_tool_names = set()  # Track rejected tool names to exclude from followup

    for tc in tool_calls:
        func_name = tc["function"]["name"]
        func_args = tc["function"].get("arguments", {})
        if isinstance(func_args, str):
            try:
                func_args = json.loads(func_args)
            except json.JSONDecodeError:
                func_args = {}

        # Defensive check: Ollama native tool calls can occasionally return
        # a dict for "name" instead of a string (malformed response).
        # Treat it as a rejected tool call so JARVIS falls back gracefully.
        if not isinstance(func_name, str):
            print(f"[JARVIS Tool] REJECTED: malformed tool call name {func_name} — not a string")
            rejected_tool_names.add(str(func_name))
            all_results.append((str(func_name), "Tool call rejected: malformed function name. Respond conversationally instead.", True))
            any_needs_followup = True
            continue

        # Intercept hallucinated verb-based tool names for Bluetooth
        if func_name in ["pair_bluetooth", "connect_bluetooth", "scan_bluetooth", "disconnect_bluetooth", "unpair_bluetooth"]:
            if "action" not in func_args:
                func_args["action"] = func_name.split("_")[0]
            func_name = "control_bluetooth"

        is_valid, error_msg = _validate_tool_call(func_name, func_args, user_input)
        if not is_valid:
            print(f"[JARVIS Tool] REJECTED: {func_name}({func_args}) — {error_msg}")
            rejected_tool_names.add(func_name)
            all_results.append((func_name, f"Tool call rejected: {error_msg}. Respond conversationally instead.", True))
            any_needs_followup = True
            continue

        print(f"[JARVIS Tool] {func_name}({func_args})")
        result, needs_followup = execute_tool_call(func_name, func_args)
        all_results.append((func_name, result, needs_followup))
        if needs_followup:
            any_needs_followup = True

    if any_needs_followup:
        tool_results_text = "\n".join([f"[{name}] {res}" for name, res, _ in all_results])
        print(f"[JARVIS Tool] Results received, generating response...")

        # Only include VALID (executed) tool calls in the followup message.
        # Rejected tool calls must not be passed back to Ollama (causes 400 Bad Request).
        # Also guard against malformed calls where name is a dict (unhashable).
        valid_tool_calls = [
            tc for tc in tool_calls
            if isinstance(tc["function"]["name"], str) and tc["function"]["name"] not in rejected_tool_names
        ]
        
        assistant_msg = {"role": "assistant", "content": full_reply}
        if valid_tool_calls:
            assistant_msg["tool_calls"] = valid_tool_calls
        messages.append(assistant_msg)
        messages.append({"role": "tool", "content": tool_results_text})

        followup_reply, _ = _stream_ollama(messages, tools=None)
        return followup_reply
    else:
        spoken_results = []
        for name, result, _ in all_results:
            if result:
                silent_keywords = [
                    "api:", "sent play", "sent pause", "sent next", "sent previous",
                    "muted", "unmuted", "set volume", "increased volume", "decreased volume",
                    "set brightness", "increased brightness", "decreased brightness",
                    "launched", "opened", "searched for",
                    "minimized", "maximized", "closed", "restored",
                    "copied", "pasted", "cut", "selected all", "rename",
                    "emptied", "created new folder", "sent delete", "deleted"
                ]
                should_speak = not any(kw in result.lower() for kw in silent_keywords)
                if "error" in result.lower() or "failed" in result.lower() or "could not" in result.lower():
                    should_speak = True

                if should_speak:
                    print(f"[JARVIS Tool] {result}")
                    speak(result)
                    spoken_results.append(result)
                else:
                    spoken_results.append(result)
        
        if full_reply:
            return full_reply
        elif spoken_results:
            return "\n".join(spoken_results)
        else:
            return "Executed silently."

def is_failure_or_retry_report(text):
    """Detect if the user is indicating that a previous action failed or did not work."""
    text_lower = text.lower().strip()
    fail_keywords = ["did not", "didn't", "failed", "not working", "retry", "try again", "didn't", "not playing", "not opening", "did not play", "did not open", "did not work", "no response"]
    return any(kw in text_lower for kw in fail_keywords)


def _is_status_check(text: str) -> bool:
    """Detect if user is asking about research task status."""
    text_lower = text.lower().strip()
    status_keywords = [
        "what happened to my research",
        "did it finish",
        "did the research finish",
        "status of my research",
        "research status",
        "how is the research",
        "any update on the research",
        "is the research done",
        "research complete",
        "research finished",
    ]
    return any(kw in text_lower for kw in status_keywords)


def _format_research_status(status: dict) -> str:
    """Format research status dict into a natural sentence for TTS."""
    if not status or not status.get("active"):
        # Check if there's a completed/failed status we can report
        if status and status.get("topic"):
            if status.get("stage") == "done":
                return f"The research on {status['topic']} is complete. Saved to {status.get('report_path', 'your Desktop')}."
            elif status.get("stage") == "error":
                return f"The research on {status['topic']} failed: {status.get('error', 'unknown error')}."
        return "No active research task to check."
    
    stage = status.get("stage", "unknown")
    topic = status.get("topic", "unknown topic")
    progress = status.get("stage_progress", "")
    
    stage_messages = {
        "decompose": "Breaking down the topic '" + topic + "' into search queries...",
        "search": "Searching for '" + topic + "' \u2014 " + (progress or "querying sources") + "...",
        "synthesize": "Synthesizing the report on '" + topic + "'...",
        "save": "Saving the research report on '" + topic + "'...",
        "done": "Research on '" + topic + "' is complete. Saved to " + status.get("report_path", "your Desktop") + ".",
        "error": "The research on '" + topic + "' failed: " + status.get("error", "unknown error") + ".",
    }
    
    return stage_messages.get(stage, "Research on '" + topic + "' is in progress (" + stage + ").")


def build_live_context(jarvis_state):
    """Build the runtime context string cleanly without code-like keys."""
    from datetime import datetime
    
    # Natural language context — avoids tool hallucination from structured syntax
    ctx = "JARVIS Operational Parameters:\n"
    ctx += f"Speech-to-Text engine is {jarvis_state.get('stt_model', 'Whisper')} running on {jarvis_state.get('stt_device', 'Processor')}.\n"
    ctx += f"Active Language Model backend is {jarvis_state.get('llm_backend', 'Cloud Backend')}.\n"
    ctx += f"Current system time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    return ctx


def ensure_custom_ollama_model():
    """Create a custom model in Ollama with the baked-in system prompt to avoid sending it in every query."""
    global OLLAMA_MODEL, SYSTEM_PROMPT, SYSTEM_PROMPT_BAKED
    
    # Wait for Ollama server to start responding if it was just launched
    tags_url = OLLAMA_URL.replace("/chat", "") + "/tags"
    print(f"[JARVIS] Waiting for Ollama server to be ready...")
    for attempt in range(15):
        try:
            res = _ollama_session.get(tags_url, timeout=2)
            if res.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)

    print(f"[JARVIS] Creating/updating custom model in Ollama with baked-in system prompt...")
    try:
        base_model = OLLAMA_MODEL
        if base_model == "jarvis_model":
            base_model = "gemma4:12b-nvfp4"
            
        custom_model = "jarvis_model"
        
        # Call Ollama API to create model: POST /api/create
        create_url = OLLAMA_URL.replace("/chat", "") + "/create"
        response = _ollama_session.post(
            create_url, 
            json={
                "model": custom_model,
                "from": base_model,
                "system": SYSTEM_PROMPT,
                "stream": False
            },
            timeout=30
        )
        if response.status_code == 200:
            print(f"[JARVIS] Custom model '{custom_model}' created successfully.")
            OLLAMA_MODEL = custom_model
            SYSTEM_PROMPT_BAKED = True
        else:
            print(f"[JARVIS Warning] Failed to create custom model (status {response.status_code}): {response.text}")
    except Exception as e:
        print(f"[JARVIS Warning] Could not create custom Ollama model: {e}")


# ==========================================================
# MAIN LOOP
# ==========================================================
def main():
    """JARVIS core loop — listen, think, speak, repeat."""
    from datetime import datetime
    from core.groq_brain import groq_think_and_speak, GroqUnavailable

    # -- STARTUP (minimal) --
    print("[JARVIS] Initializing...")

    # Preload installed apps list in background for faster first app launch
    print("[JARVIS] Preloading app list in background...")
    from core.fast_lane import get_installed_apps
    threading.Thread(target=get_installed_apps, daemon=True).start()

    print("[JARVIS] Opening microphone...")
    try:
        audio_interface = pyaudio.PyAudio()
    except Exception as e:
        print(f"[JARVIS] ERROR: Could not initialize microphone — {e}")
        print("[JARVIS] Please check your audio device and try again.")
        return

    # -- ADAPTIVE MIC CALIBRATION --
    print("[JARVIS] Calibrating microphone... (please stay quiet for 2 seconds)")
    speak("Please wait 2 seconds to calibrate mic.")
    wait_for_speech()  # Wait for TTS audio to fully stop before sampling ambient noise
    time.sleep(0.5)    # Extra pause to let TTS residual audio decay from the mic
    
    # Get VAD model for calibration (filters out speech-like noise)
    vad_model = get_vad_model()
    
    speech_threshold, amb_mean, amb_max = calibrate_mic(audio_interface, vad_model=vad_model, use_aec=True)
    print(f"[JARVIS] Mic calibrated — ambient mean={amb_mean:.0f}, peak={amb_max:.0f} → speech threshold={speech_threshold}")
    speak(f"Calibration complete. Speech threshold set to {speech_threshold}.")

    print("[JARVIS] All systems online. Listening.")

    # -- MEMORY SYSTEM INIT (lazy) --
    global SYSTEM_PROMPT
    memory = get_memory_manager()
    
    # Bake stable identity into system prompt for massive KV cache reuse
    if memory:
        stable_mem = memory.get_stable_context()
        if stable_mem:
            SYSTEM_PROMPT += "\n\n" + stable_mem

    ensure_custom_ollama_model()

    # -- RUNTIME STATE (JARVIS self-awareness) --
    jarvis_state = {
        "stt_device": "MLX/MPS",
        "stt_model": "MLX Whisper (large-v3-turbo)",
        "llm_model": GROQ_MODEL if GROQ_API_KEY else OLLAMA_MODEL,
        "llm_backend": "Groq (cloud)" if GROQ_API_KEY else "Ollama (local)",
        "tts_engine": "Kokoro-MLX",
        "tts_voice": f"{KOKORO_VOICE} (EN)",
        "mic_threshold": speech_threshold,
        "start_time": datetime.now(),
    }

    # Time-aware greeting
    hour = datetime.now().hour
    if hour < 12:
        greeting = "All systems online. Good morning sir."
    elif hour < 17:
        greeting = "All systems online. Good afternoon sir."
    elif hour < 21:
        greeting = "All systems online. Good evening sir."
    else:
        greeting = "All systems online. Running late sir?."

    speak(greeting)

    history = []
    full_session_history = []  # Unbounded — for memory consolidation
    listen_count = 0
    RECALIBRATE_INTERVAL = 50  # Re-calibrate mic every N listen cycles

    from config.config import WAKE_WORDS

    try:
        while True:
            # Wait for any previous speech to finish before listening
            wait_for_speech()

            # Periodic re-calibration to adapt to changing noise environments
            listen_count += 1
            if listen_count % RECALIBRATE_INTERVAL == 0:
                speech_threshold, _, _ = calibrate_mic(audio_interface, vad_model=vad_model, use_aec=True)
                print(f"[JARVIS] Re-calibrated — threshold={speech_threshold}")
                jarvis_state["mic_threshold"] = speech_threshold

            # -- LISTEN (Continuous mode: wake word + command in single stream) --
            # Initialize heavy components on first actual use
            ensure_first_use_initialized()
            
            # Get loaded components
            vad_model = get_vad_model()
            stt_engine = get_stt_engine()
            
            # Small delay after TTS finishes to let residual audio decay from mic
            time.sleep(0.15)
            
            lang = WHISPER_LANGUAGE or "en"
            transcriber = BackgroundTranscriber(stt_engine, audio_interface, lang, history=history, live_context=build_live_context(jarvis_state))
            transcriber.start()

            # Use continuous listening to get multiple utterances in one stream
            got_wake_word = False
            command_text = None

            for frames, is_final in listen(audio_interface, speech_threshold, vad_model, transcriber, continuous=True, use_aec=True):
                if frames is None:
                    continue

                # Transcribe this utterance
                try:
                    text, detected_lang = transcriber.stop_and_get(frames)
                except Exception as e:
                    print(f"[JARVIS] Transcription error: {e}")
                    # Restart transcriber for next utterance
                    transcriber = BackgroundTranscriber(stt_engine, audio_interface, lang, history=history, live_context=build_live_context(jarvis_state))
                    transcriber.start()
                    continue

                if text is None:
                    # Restart transcriber for next utterance
                    transcriber = BackgroundTranscriber(stt_engine, audio_interface, lang, history=history, live_context=build_live_context(jarvis_state))
                    transcriber.start()
                    continue

                # -- WAKE WORD CHECK (via Whisper transcript) --
                clean_text = text.lower().replace('.', '').replace(',', '').replace('!', '').replace('?', '').replace('-', '').strip()

                # 100% Bulletproof Wake Word Check using actual text
                if not any(w in clean_text for w in ["jarvis"]):
                    # Not a wake word, restart transcriber and continue listening
                    transcriber = BackgroundTranscriber(stt_engine, audio_interface, lang, history=history, live_context=build_live_context(jarvis_state))
                    transcriber.start()
                    continue

                # -- CASE: Just the wake word (user paused, waiting to give command) --
                if clean_text in WAKE_WORDS:
                    print(f"\n[You]    {text}")
                    got_wake_word = True
                    # Don't speak "Yes sir?" - just continue listening in same stream
                    print("[JARVIS] Listening for command...")
                    # Restart transcriber for next utterance
                    transcriber = BackgroundTranscriber(stt_engine, audio_interface, lang, history=history, live_context=build_live_context(jarvis_state))
                    transcriber.start()
                    continue

                # This is the actual command (either after wake word or standalone with wake word)
                command_text = text
                print(f"\n[You]    {command_text}")
                break  # Exit the continuous listen loop

            # Stop the transcriber
            transcriber.stop_and_get([])

            if command_text is None:
                continue

            text = command_text


            # -- TRIVIAL FAST LANE (instant execution for simple commands) --
            try:
                from core.fast_lane import try_trivial_fast_lane
                success, fast_msg = try_trivial_fast_lane(text)
                if success:
                    if fast_msg:
                        print(f"[JARVIS Fast Lane] {fast_msg}")
                        # Don't speak API confirmations for instant commands
                        silent_keywords = ["api:", "sent play", "sent pause", "sent next", "sent previous", "muted", "unmuted"]
                        should_speak = not any(kw in fast_msg.lower() for kw in silent_keywords)
                        if "error" in fast_msg.lower() or "failed" in fast_msg.lower():
                            should_speak = True
                        if should_speak:
                            speak(fast_msg)
                    else:
                        print("[JARVIS Fast Lane] Action executed silently.")

                    history.append({"role": "user", "content": text})
                    history.append({"role": "jarvis", "content": fast_msg or "Executed."})
                    full_session_history.append({"role": "user", "content": text})
                    full_session_history.append({"role": "jarvis", "content": fast_msg or "Executed."})
                    if len(history) > MAX_HISTORY_TURNS:
                        history = history[-MAX_HISTORY_TURNS:]
                    continue
            except Exception as e:
                print(f"[JARVIS Fast Lane] Error: {e}")

            # -- FAST LANE: compound/structured commands (parse_intent handles multi-action)
            try:
                from core.fast_lane import process_fast_lane
                success, fast_msg = process_fast_lane(text, history)
                if success:
                    if fast_msg:
                        print(f"[JARVIS Fast Lane] {fast_msg}")
                        silent_keywords = ["api:", "sent play", "sent pause", "sent next", "sent previous", "muted", "unmuted"]
                        should_speak = not any(kw in fast_msg.lower() for kw in silent_keywords)
                        if "error" in fast_msg.lower() or "failed" in fast_msg.lower():
                            should_speak = True
                        if should_speak:
                            speak(fast_msg)
                    else:
                        print("[JARVIS Fast Lane] Action executed silently.")

                    history.append({"role": "user", "content": text})
                    history.append({"role": "jarvis", "content": fast_msg or "Executed."})
                    full_session_history.append({"role": "user", "content": text})
                    full_session_history.append({"role": "jarvis", "content": fast_msg or "Executed."})
                    if len(history) > MAX_HISTORY_TURNS:
                        history = history[-MAX_HISTORY_TURNS:]
                    continue
            except Exception as e:
                print(f"[JARVIS Fast Lane] Error: {e}")

            # -- STATUS CHECK PRE-CHECK (before intent classification) --
            # Phrases like "what happened to my research", "did it finish", "status of research"
            # should read the real research_status dict, not go through the LLM classifier
            try:
                from core.deep_research import get_research_status, is_research_active
                if is_research_active() or _is_status_check(text):
                    status = get_research_status()
                    status_msg = _format_research_status(status)
                    print(f"[JARVIS] Research status check: {status}")
                    speak(status_msg)
                    history.append({"role": "user", "content": text})
                    history.append({"role": "jarvis", "content": status_msg})
                    full_session_history.append({"role": "user", "content": text})
                    full_session_history.append({"role": "jarvis", "content": status_msg})
                    if len(history) > MAX_HISTORY_TURNS:
                        history = history[-MAX_HISTORY_TURNS:]
                    continue
            except Exception as e:
                # Don't let status-check errors break the normal flow
                print(f"[JARVIS] Status check error (non-fatal): {e}")

            # -- GROQ CLOUD BRAIN (Primary) --
            if GROQ_API_KEY:
                try:
                    print("[JARVIS] Thinking via Groq...")
                    # groq_think_and_speak already streams, prints, and speaks chunks automatically
                    response = groq_think_and_speak(history, text, live_context=transcriber.live_context)
                    
                    # REMOVED: groq_think_and_speak already handles streaming output and TTS
                    # print(f"[JARVIS] {response}")
                    # speak(response)

                    # Keep the history loops intact so Jarvis remembers context
                    history.append({"role": "user", "content": text})
                    history.append({"role": "jarvis", "content": response})
                    full_session_history.append({"role": "user", "content": text})
                    full_session_history.append({"role": "jarvis", "content": response})
                    if len(history) > MAX_HISTORY_TURNS:
                        history = history[-MAX_HISTORY_TURNS:]
                    continue
                except GroqUnavailable as e:
                    print(f"[JARVIS] Groq unreachable ({e}), falling back to local model")
                    jarvis_state["llm_model"] = "Ollama (local, offline fallback)"
                    jarvis_state["llm_backend"] = "Ollama (local, offline fallback)"
                except Exception as e:
                    print(f"[JARVIS] Groq error: {e}, falling back to local model")
                    jarvis_state["llm_model"] = "Ollama (local, offline fallback)"
                    jarvis_state["llm_backend"] = "Ollama (local, offline fallback)"

            # -- INTELLIGENT INTENT CLASSIFICATION (model-driven, no keywords) --
            print("[JARVIS] Classifying intent...")
            classification = classify_intent(text, history)
            cat = classification.get("category", "CONVERSATION")
            confidence = classification.get("confidence", 0.5)
            reasoning = classification.get("reasoning", "")
            followup = classification.get("followup_suggestion")
            
            print(f"[JARVIS] Intent: {cat} (confidence: {confidence:.2f}) - {reasoning}")
            
            routing = get_routing_decision(classification)
            route_type = routing[0]
            route_data = routing[1]

            # -- HANDLE FOLLOWUP SUGGESTION --
            if followup:
                print(f"[JARVIS] Proactive suggestion: {followup}")
                speak(followup)
                # Add to history so it's remembered
                history.append({"role": "user", "content": text})
                history.append({"role": "jarvis", "content": followup})
                full_session_history.append({"role": "user", "content": text})
                full_session_history.append({"role": "jarvis", "content": followup})
                if len(history) > MAX_HISTORY_TURNS:
                    history = history[-MAX_HISTORY_TURNS:]
                continue

            # -- ROUTING --
            if route_type == "fast_tool":
                # Fast model with tools - use classifier's suggested_tools to filter catalog
                suggested_tools = route_data  # list of tool names from classifier
                if suggested_tools:
                    # Filter JARVIS_TOOLS to only include suggested tools
                    tools_to_pass = [t for t in JARVIS_TOOLS if t["function"]["name"] in suggested_tools]
                    # Fall back to full catalog if nothing matched (shouldn't happen, but defensive)
                    if not tools_to_pass:
                        print(f"[JARVIS] Warning: suggested_tools {suggested_tools} matched no tools, using full catalog")
                        tools_to_pass = JARVIS_TOOLS
                else:
                    tools_to_pass = JARVIS_TOOLS
                query_embedding = None
                
            elif route_type == "complex":
                # Escalate to complex model
                print(f"[JARVIS] Escalating to complex model: {route_data}")
                if route_data == "deep research task":
                    # Extract save path if mentioned
                    save_path = None
                    if "desktop" in text.lower():
                        save_path = str(Path.home() / "Desktop")
                    
                    # Start background research
                    def on_research_complete(success, result):
                        if success:
                            msg = f"Research complete. Saved to {result.get('file_path', 'Desktop')}"
                        else:
                            msg = f"Research failed: {result}"
                        print(f"[JARVIS] {msg}")
                        speak(msg)
                    
                    start_background_research(
                        query=text,
                        save_path=save_path,
                        context=transcriber.live_context,
                        history=history,
                        on_complete=on_research_complete
                    )
                    speak("Research started. I'll work on this in the background.")
                    continue
                else:
                    # Complex model for other tasks
                    tools_to_pass = JARVIS_TOOLS
                    # Use complex model call
                    response, error = call_complex_model(
                        messages=build_messages(history, text, transcriber.live_context),
                        tools=tools_to_pass,
                        stream=True
                    )
                    if error:
                        speak(f"Complex model error: {error}")
                        continue
                    # Stream response from complex model
                    # ... need to handle streaming response
                    pass
                    
            elif route_type == "ask_escalate":
                # Ask user if they want to escalate
                speak(f"I think this task needs more intelligence. {route_data} Should I switch to the larger model?")
                # Wait for yes/no - would need another listen cycle
                # For now, fall through to fast model
                tools_to_pass = JARVIS_TOOLS
                query_embedding = None
                
            else:  # conversation
                # Pure conversation, no tools
                tools_to_pass = None
                query_embedding = None

            # -- BUILD DYNAMIC CONTEXT --
            live_context = transcriber.live_context
            
            if memory and tools_to_pass:
                try:
                    dynamic_mem = memory.get_dynamic_context(text, query_embedding=query_embedding)
                    if dynamic_mem:
                        live_context += "\n\n" + dynamic_mem
                except Exception as e:
                    print(f"[JARVIS] Dynamic memory context error: {e}")

            # -- THINK & SPEAK (fast model with tools) --
            try:
                response = think_and_speak(history, text, live_context, tools_to_pass=tools_to_pass)
            except requests.exceptions.ConnectionError:
                print("[JARVIS] Ollama is not running. Please start Ollama and try again.")
                speak("Ollama is not running sir. Please start it.")
                continue
            except Exception as e:
                import traceback
                print("[JARVIS] Detailed Traceback:")
                traceback.print_exc()
                print(f"[JARVIS] Error: {e}")
                continue

            # -- HISTORY --
            history.append({"role": "user", "content": text})
            history.append({"role": "jarvis", "content": response})
            full_session_history.append({"role": "user", "content": text})
            full_session_history.append({"role": "jarvis", "content": response})
            if len(history) > MAX_HISTORY_TURNS:
                history = history[-MAX_HISTORY_TURNS:]

            # -- MID-SESSION MEMORY CONSOLIDATION --
            if memory:
                try:
                    memory.check_mid_session_consolidation(
                        full_session_history,
                        turn_interval=MEMORY_MID_SESSION_INTERVAL,
                    )
                except Exception as e:
                    print(f"[JARVIS] Mid-session consolidation error: {e}")

    except KeyboardInterrupt:
        # -- MEMORY CONSOLIDATION AT SHUTDOWN --
        if memory and full_session_history:
            print("\n[JARVIS] Consolidating memories...")
            try:
                memory.on_session_end(
                    full_session_history,
                    session_start_time=jarvis_state.get("start_time"),
                )
            except Exception as e:
                print(f"[JARVIS] Memory consolidation error: {e}")

        print("[JARVIS] Going offline. Goodbye, sir.")
        speak("Going offline. Goodbye sir.")
        # Wait for the goodbye message to finish playing before killing the threads
        wait_for_speech()
    finally:
        audio_interface.terminate()
        cleanup_all()


if __name__ == "__main__":
    main()
