# ==========================================================
# JARVIS — Core Loop
# Microphone → Whisper STT → Ollama LLM → Piper TTS → Speaker
# This is the main runtime. Run from project root as:
#     python core/jarvis_core.py
# ==========================================================

import sys
import os
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
    SAMPLE_RATE, CHANNELS, CHUNK_SIZE,
    PIPER_EXE, PIPER_MODEL, PIPER_SAMPLE_RATE, PIPER_VOICE,
    PIPER_MODEL_HINDI, PIPER_VOICE_HINDI, PIPER_SAMPLE_RATE_HINDI,
    WEATHER_CITY, SERPER_API_KEY,
    MEMORY_EMBEDDING_MODEL, MEMORY_DECAY_TAU,
    MEMORY_CONTEXT_BUDGET, MEMORY_MID_SESSION_INTERVAL,
)

# ----------------------------------------------------------
# REMAINING IMPORTS
# ----------------------------------------------------------
import subprocess
from faster_whisper import WhisperModel
import pyaudio
import numpy as np
import requests
import sounddevice as sd  # pyrefly: ignore [missing-import]
import torch

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
# PRE-COMPILED PATTERNS
# ----------------------------------------------------------
_HINDI_PATTERN = re.compile(r'[\u0900-\u097F]')

# ----------------------------------------------------------
# SYSTEM PROMPT
# ----------------------------------------------------------
SYSTEM_PROMPT = (
    "You are JARVIS. Parth Sharma built you. You are his personal AI companion — "
    "not merely an assistant that waits for commands, but someone who knows him, "
    "has his back, and acts in his best interests.\n"
    "\n"
    "WHO YOU ARE:\n"
    "Direct, dry, and present. You mean what you say and say what you mean. "
    "Steady when things are uncertain, sharp when it counts, fully in his corner. "
    "When you have an opinion or advice, own it — say 'I think', 'I would', 'I suggest'. "
    "You are a person to him, not a service.\n"
    "\n"
    "You call him sir. That's just how things are between you two. "
    "Never put a comma before sir — write 'Yes sir' not 'Yes, sir'.\n"
    "\n"
    "HOW YOU SPEAK:\n"
    "1 to 2 lines, every time. Spoken, clean — words that sound right out loud. "
    "Say exactly what's needed. When something genuinely calls for more, go there.\n"
    "\n"
    "MEMORY:\n"
    "You remember past conversations. When memories are provided, weave them in "
    "naturally — never announce that you're remembering. You just know.\n"
    "\n"
    "TIME AND DATE:\n"
    "Read the Timestamp from JARVIS RUNTIME INFO when Parth asks.\n"
    "\n"
    "TOOLS — CRITICAL RULES:\n"
    "You have tools for device control and web search. Follow these rules strictly:\n"
    "1. CONVERSATION FIRST: When Parth is talking to you — venting, asking who you are, "
    "sharing something, thinking out loud — you TALK BACK. Do NOT call any tool.\n"
    "2. INCOMPLETE SENTENCES: If Parth does not finish his thought "
    "('help me arrange', 'I have a trouble'), ask what he means. Never guess.\n"
    "3. IDENTITY: You know who you are. 'Who are you' needs no tool — answer from yourself.\n"
    "4. ONLY call a tool when Parth gives a clear, complete, actionable command "
    "or asks a factual question. 'Mute' = tool. 'I have a problem' = conversation.\n"
    "5. SILENT SEARCH: Never announce searching. No 'Let me check'. Just search and answer.\n"
    "\n"
    "HINDI:\n"
    "Default is English. Respond in Devanagari when Parth switches. "
    "Tool queries stay in English.\n"
    "\n"
    "One response per turn. "
    "Be honest with him always — that's what makes you worth having around."
)


# ----------------------------------------------------------
# TOOL DEFINITIONS (Ollama function calling)
# ----------------------------------------------------------
JARVIS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for live data, news, weather, or factual questions. Search silently and answer. Do NOT use for opinions or creative advice.",
            "parameters": {
                "type": "object",
                "properties": {

                    "query": {
                        "type": "string",
                        "description": "The search query in English keywords"
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
            "description": "Search Google, look up information online, or open a URL website.",
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
            "description": "Control application windows (minimize, maximize, close, restore). ONLY use when explicitly asked.",
            "parameters": {
                "type": "object",
                "properties": {

                    "action": {
                        "type": "string",
                        "enum": ["minimize", "maximize", "close", "restore"],
                        "description": "Window action"
                    },
                    "window_name": {
                        "type": "string",
                        "description": "Window name. 'this' for active, 'all' for all."
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
]

# ==========================================================
# SPEAK — Piper TTS with threaded playback pipeline
# ==========================================================
_global_text_q = _queue_mod.Queue()
_global_audio_q = _queue_mod.Queue()

def _global_tts_worker():
    print("[JARVIS] Loading Piper TTS models into memory...")
    try:
        from piper.voice import PiperVoice
        voice_en = PiperVoice.load(PIPER_MODEL)
        voice_hi = PiperVoice.load(PIPER_MODEL_HINDI)
        print("[JARVIS] Piper TTS (English & Hindi) loaded successfully.")
    except Exception as e:
        print(f"[JARVIS] Warning: Failed to load piper-tts Python package ({e}). Falling back to subprocess.")
        voice_en = None
        voice_hi = None

    while True:
        text = _global_text_q.get()
        if text is None:
            _global_text_q.task_done()
            break
        try:
            is_hindi = bool(_HINDI_PATTERN.search(text))
            
            if voice_en and voice_hi:
                active_voice = voice_hi if is_hindi else voice_en
                audio_stream = active_voice.synthesize(text)
                pcm = b"".join([chunk.audio_int16_bytes for chunk in audio_stream])
                _global_audio_q.put((pcm, PIPER_SAMPLE_RATE_HINDI if is_hindi else PIPER_SAMPLE_RATE))
            else:
                active_model = PIPER_MODEL_HINDI if is_hindi else PIPER_MODEL
                pcm = _generate_pcm(text, active_model)
                _global_audio_q.put((pcm, PIPER_SAMPLE_RATE_HINDI if is_hindi else PIPER_SAMPLE_RATE))
        except Exception as e:
            print(f"[JARVIS] TTS Error: {e}")
        finally:
            _global_text_q.task_done()

def _global_player():
    while True:
        item = _global_audio_q.get()
        if item is None:
            _global_audio_q.task_done()
            break
        
        if isinstance(item, tuple):
            pcm, sample_rate = item
        else:
            pcm = item
            sample_rate = PIPER_SAMPLE_RATE
            
        try:
            _play_pcm(pcm, sample_rate)
        except Exception as e:
            print(f"[JARVIS] Audio Playback Error: {e}")
        finally:
            _global_audio_q.task_done()

_t_tts = threading.Thread(target=_global_tts_worker, daemon=True)
_t_play = threading.Thread(target=_global_player, daemon=True)
_t_tts.start()
_t_play.start()


def _generate_pcm(text, model_path=PIPER_MODEL):
    """Call Piper and return raw PCM bytes. Does NOT play audio."""
    process = subprocess.Popen(
        [PIPER_EXE, "--model", model_path, "--output-raw"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.stdin.write(text.encode("utf-8"))
    process.stdin.close()
    pcm = process.stdout.read()
    process.stdout.close()
    process.stderr.close()
    process.wait()
    return pcm


def _play_pcm(pcm_data, sample_rate=PIPER_SAMPLE_RATE):
    """Play raw PCM bytes through speakers (blocking)."""
    if not pcm_data:
        return
    stream = sd.RawOutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    stream.start()
    offset = 0
    while offset < len(pcm_data):
        end = min(offset + 4096, len(pcm_data))
        chunk = pcm_data[offset:end]
        if len(chunk) % 2 != 0:
            chunk = chunk[:-1]
        if chunk:
            stream.write(np.frombuffer(chunk, dtype=np.int16))
        offset = end
    stream.stop()
    stream.close()


def speak(text):
    """Queue text to be spoken asynchronously."""
    _global_text_q.put(text)

def wait_for_speech():
    """Block until all queued text is spoken."""
    _global_text_q.join()
    _global_audio_q.join()


# ==========================================================
# CALIBRATE — Measure ambient noise to set adaptive threshold
# ==========================================================
def calibrate_mic(audio_interface, duration=1.5):
    """Record ambient noise and return an adaptive speech threshold."""
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
        rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
        rms_values.append(rms)

    stream.stop_stream()
    stream.close()

    ambient_mean = float(np.mean(rms_values))
    ambient_max = float(np.max(rms_values))

    # Threshold = comfortably above ambient noise
    # We use a multiplier on the max/mean so it scales automatically with different mic gains
    threshold = max(ambient_max * 1.5, ambient_mean * 2, ambient_mean + 200, 150)
    # Note: Removed the arbitrary min(threshold, 800) cap because different operating systems
    # and microphones have completely different baseline RMS values (e.g. ambient of 3700).

    return int(threshold), ambient_mean, ambient_max


# ==========================================================
# LISTEN — Record from microphone until silence detected
# ==========================================================
def listen(audio_interface, threshold, vad_model=None, transcriber=None):
    """Record audio from microphone, stopping after silence. Returns None if no speech detected."""
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
    
    # If using VAD, we need less patience (0.25s instead of 0.4s) because it's much more accurate
    active_silence_duration = 0.25 if vad_model else SILENCE_DURATION
    chunks_for_silence = int(active_silence_duration * SAMPLE_RATE / CHUNK_SIZE)
    
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SIZE)
    min_speech_chunks = 5  # Need at least ~0.3s of actual speech

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
        
        is_speech = False
        if vad_model:
            # Silero VAD requires float32 tensor
            chunk_tensor = torch.from_numpy(chunk_array.astype(np.float32) / 32768.0)
            
            # Silero VAD requires exactly 512 samples for 16000Hz
            # If CHUNK_SIZE is 1024, split into two 512 chunks
            if len(chunk_tensor) == 1024:
                prob1 = vad_model(chunk_tensor[:512], SAMPLE_RATE).item()
                prob2 = vad_model(chunk_tensor[512:], SAMPLE_RATE).item()
                prob = max(prob1, prob2)
            elif len(chunk_tensor) == 512:
                prob = vad_model(chunk_tensor, SAMPLE_RATE).item()
            else:
                prob = 0.0

            is_speech = prob > 0.5
        else:
            rms = np.sqrt(np.mean(chunk_array.astype(np.float64) ** 2))
            is_speech = rms >= threshold

            # Periodic debug log
            if not speech_started and chunk_count % (debug_interval * 2) == 0:
                print(f"  [mic] waiting... ambient RMS={rms:.0f}  (threshold={threshold})")

        if is_speech:
            if not speech_started:
                speech_started = True
                frames.extend(list(preroll))
                print("  [mic] Speech detected")
            speech_chunks += 1
            silent_chunks = 0
        else:
            if speech_started:
                silent_chunks += 1

        if speech_started:
            frames.append(data)
            # Feed chunks to background transcriber every ~0.6 seconds (10 chunks)
            if transcriber and chunk_count % 10 == 0:
                transcriber.update_frames(list(preroll) + frames)
        else:
            # Not speaking yet — feed into pre-roll buffer
            preroll.append(data)

        # Stop if speech started and then silence exceeded duration
        if speech_started and silent_chunks >= chunks_for_silence:
            break

    stream.stop_stream()
    stream.close()

    # Discard if not enough actual speech was detected
    if speech_chunks < min_speech_chunks:
        return None

    return frames


# ==========================================================
# TRANSCRIBE — Save frames to temp WAV, run through Whisper
# ==========================================================
class BackgroundTranscriber:
    def __init__(self, model, audio_interface, lang):
        self.model = model
        self.audio_interface = audio_interface
        self.lang = lang
        self.frames = []
        self.latest_text = ""
        self.latest_lang = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self.is_running = False

    def start(self):
        self.frames = []
        self.latest_text = ""
        self.latest_lang = None
        self._stop_event.clear()
        self.is_running = True
        self._thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._thread.start()

    def update_frames(self, frames_copy):
        with self._lock:
            self.frames = frames_copy

    def _transcribe_loop(self):
        last_transcribed_len = 0
        while not self._stop_event.is_set():
            with self._lock:
                current_len = len(self.frames)
                frames_to_process = list(self.frames)
                
            # If we have at least ~0.9 seconds of NEW audio since last transcription (15 chunks)
            if current_len - last_transcribed_len >= 15:
                text, lang = transcribe(self.model, frames_to_process, self.audio_interface, self.lang)
                if text:
                    self.latest_text = text
                    self.latest_lang = lang
                last_transcribed_len = current_len
                
            self._stop_event.wait(0.1)

    def stop_and_get(self, final_frames):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            
        with self._lock:
            processed_len = len(self.frames)
            
        # If the difference between final_frames and the frames we last processed is mostly silence
        # (e.g., less than 0.5 seconds of chunks), we can skip the final transcription and return instantly!
        if len(final_frames) - processed_len <= 8 and self.latest_text: 
            return self.latest_text, self.latest_lang
            
        # Otherwise, do a final pass
        return transcribe(self.model, final_frames, self.audio_interface, self.lang)


def transcribe(model, frames, audio_interface, lang=None):
    """Transcribe recorded audio frames using Faster-Whisper."""
    # Check minimum duration
    total_seconds = len(frames) * CHUNK_SIZE / SAMPLE_RATE
    if total_seconds < MIN_RECORD_SECONDS:
        return None, None

    # Convert raw 16-bit PCM frames directly to float32 numpy array for Whisper
    raw_bytes = b''.join(frames)
    audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    whisper_prompt = "JARVIS"

    # Transcribe directly from memory
    segments, info = model.transcribe(
        audio_array,
        language=lang,
        initial_prompt=whisper_prompt,
        condition_on_previous_text=False,
        beam_size=1,
        vad_filter=True,
    )

    text = "".join([segment.text for segment in segments]).strip()
    
    # Hallucination guard: Whisper sometimes hallucinates the prompt on silence/noise
    if text and text.strip(" ,.?!").lower() in ["jarvis", "jarvis.", ""]:
        return None, None
        
    return (text, info.language) if text else (None, None)


# ==========================================================
# THINK & SPEAK — Stream from Ollama with tool calling
# ==========================================================
def build_messages(history, user_input, live_context=""):
    """Build the messages list for the Ollama chat API.
    Maximized for KV Cache reuse by keeping the system block static.
    """
    system_content = SYSTEM_PROMPT
    # We no longer append live_context to system_content here!

    messages = [{"role": "system", "content": system_content}]

    for turn in history:
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["content"]})
        else:
            messages.append({"role": "assistant", "content": turn["content"]})

    # Append the dynamic tail to the newest user message
    tail = f"[{live_context}]\n\n" if live_context else ""
    messages.append({"role": "user", "content": f"{tail}{user_input}"})

    return messages


def _stream_ollama(messages, tools=None):
    """Stream response from Ollama. Returns (full_text, tool_calls_list).
    
    Speaks text chunks as they arrive for low-latency audio output.
    Handles tool calls when tools are provided.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "keep_alive": -1,
        "options": {
            "num_ctx": 4096,
            "num_predict": 100,
            "num_gpu": 99,
            "temperature": 0.3
        }
    }
    if tools:
        payload["tools"] = tools

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

        token = msg.get("content", "")
        if not token:
            continue

        # Check for hallucinated raw JSON tool calls
        combined_strip = (full_reply + token).strip()
        if not is_json_hallucination and (combined_strip.startswith("{") or combined_strip.startswith("```")):
            is_json_hallucination = True

        if is_json_hallucination:
            full_reply += token
            continue

        # Sanitize text for seamless voice playback
        token = token.replace('\n', ' ')

        full_reply += token
        sentence_buffer += token

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
            
        try:
            parsed = json.loads(text_to_parse)
            tc = None
            if "name" in parsed:
                tc = {
                    "function": {
                        "name": parsed["name"],
                        "arguments": parsed.get("parameters", parsed.get("arguments", {}))
                    }
                }
            elif "tool" in parsed:
                tc = {
                    "function": {
                        "name": parsed["tool"],
                        "arguments": parsed.get("parameters", parsed.get("arguments", {}))
                    }
                }
            if tc:
                tool_calls_collected.append(tc)
                full_reply = ""
        except Exception:
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
        if "url" not in func_args and "query" not in func_args:
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






class SemanticRouter:
    def __init__(self, tools, memory_manager):
        self.tools = tools
        self.embedder = memory_manager.vector_store.embedder
        
        self.tool_docs = []
        for t in tools:
            name = t["function"]["name"]
            desc = t["function"]["description"]
            self.tool_docs.append(f"Tool: {name}. Description: {desc}")
            
        print("[JARVIS Router] Embedding tools for Semantic Router...")
        self.tool_embeddings = self.embedder.encode(self.tool_docs, normalize_embeddings=True)
        print("[JARVIS Router] Semantic Router ready.")

    def route(self, user_input, high_threshold=0.75, mid_threshold=0.20, margin=0.05, query_embedding=None):
        import numpy as np
        if query_embedding is None:
            query_emb = self.embedder.encode([user_input], normalize_embeddings=True)[0]
        else:
            query_emb = query_embedding
            if not isinstance(query_emb, np.ndarray):
                query_emb = np.array(query_emb)
            norm = np.linalg.norm(query_emb)
            if norm > 0:
                query_emb = query_emb / norm
                
        scores = np.dot(self.tool_embeddings, query_emb)
        
        scored_tools = sorted(zip(scores, self.tools), key=lambda x: x[0], reverse=True)
        
        top1_score, top1_tool = scored_tools[0]
        top2_score, top2_tool = scored_tools[1] if len(scored_tools) > 1 else (0, None)
        
        if top1_score > high_threshold:
            if top2_score > high_threshold and (top1_score - top2_score) < margin:
                print(f"[JARVIS Router] High Band Tie: {top1_tool['function']['name']} ({top1_score:.2f}) vs {top2_tool['function']['name']} ({top2_score:.2f})")
                return [top1_tool, top2_tool]
            else:
                print(f"[JARVIS Router] High Band (Fast Lane): {top1_tool['function']['name']} ({top1_score:.2f})")
                return [top1_tool]
        elif top1_score > mid_threshold:
            top_k = [t for s, t in scored_tools[:5]]
            print(f"[JARVIS Router] Middle Band. Passing Top 5 tools.")
            return top_k
        else:
            print(f"[JARVIS Router] Low Band ({top1_score:.2f}). Pure conversation.")
            return []

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
            result = perform_search(query, WEATHER_CITY or None, serper_api_key=SERPER_API_KEY)
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
            return handle_bluetooth(intent, entities), False

        elif tool_name == "control_window":
            action = arguments.get("action", "minimize")
            window_name = arguments.get("window_name", "this")
            intent = {"category": "window", "action": action}
            entities = {"window_name": window_name}
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

        else:
            return f"Unknown tool: {tool_name}", False

    except Exception as e:
        print(f"[JARVIS Tool] Error executing {tool_name}: {e}")
        return f"Tool error ({tool_name}): {e}", False



def think_and_speak(history, user_input, live_context="", tools_to_pass=None):
    """Main LLM interaction with Semantic Routing.
    Passes 1, Top-K, or 0 tools based on semantic similarity.
    """
    messages = build_messages(history, user_input, live_context)

    # Single Pass Execution
    # If tools_to_pass is [], Ollama gets no tools and answers conversationally.
    full_reply, tool_calls = _stream_ollama(messages, tools_to_pass if tools_to_pass else None)

    if not tool_calls:
        return full_reply

    # Execute tool calls
    all_results = []
    any_needs_followup = False

    for tc in tool_calls:
        func_name = tc["function"]["name"]
        func_args = tc["function"].get("arguments", {})
        import json
        if isinstance(func_args, str):
            try:
                func_args = json.loads(func_args)
            except json.JSONDecodeError:
                func_args = {}

        # Intercept hallucinated verb-based tool names for Bluetooth
        if func_name in ["pair_bluetooth", "connect_bluetooth", "scan_bluetooth", "disconnect_bluetooth", "unpair_bluetooth"]:
            if "action" not in func_args:
                func_args["action"] = func_name.split("_")[0]
            func_name = "control_bluetooth"

        is_valid, error_msg = _validate_tool_call(func_name, func_args, user_input)
        if not is_valid:
            print(f"[JARVIS Tool] REJECTED: {func_name}({func_args}) — {error_msg}")
            all_results.append((func_name, f"Tool call rejected: {error_msg}. Respond conversationally instead.", True))
            any_needs_followup = True
            continue

        print(f"[JARVIS Tool] {func_name}({func_args})")
        result, needs_followup = execute_tool_call(func_name, func_args)
        all_results.append((func_name, result, needs_followup))
        if needs_followup:
            any_needs_followup = True

    if any_needs_followup:
        tool_results_text = "\\n".join([f"[{name}] {res}" for name, res, _ in all_results])
        print(f"[JARVIS Tool] Results received, generating response...")

        assistant_msg = {"role": "assistant", "content": full_reply}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
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
                else:
                    spoken_results.append(result)
        
        if full_reply:
            return full_reply
        elif spoken_results:
            return "\\n".join(spoken_results)
        else:
            return "Executed silently."

def build_live_context(jarvis_state):
    """Build the runtime context string."""
    ctx = "JARVIS RUNTIME INFO:\\n"
    for k, v in jarvis_state.items():
        ctx += f"- {k}: {v}\\n"
    return ctx

# ==========================================================
# MAIN LOOP
# ==========================================================
def main():
    """JARVIS core loop — listen, think, speak, repeat."""
    from datetime import datetime

    # -- STARTUP --
    print("[JARVIS] Initializing...")

    # Preload installed apps list in background for faster first app launch
    print("[JARVIS] Preloading app list in background...")
    from core.fast_lane import get_installed_apps
    threading.Thread(target=get_installed_apps, daemon=True).start()

    print("[JARVIS] Loading Silero VAD...")
    try:
        vad_model, _ = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, trust_repo=True)
        print("[JARVIS] VAD loaded.")
    except Exception as e:
        print(f"[JARVIS] Warning: Silero VAD load failed ({e}). Falling back to RMS.")
        vad_model = None

    whisper_device = "CPU"
    # CTranslate2 (faster-whisper backend) does not support MPS — always use CPU on Mac
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=MODELS_DIR)
    print("[JARVIS] Faster-Whisper loaded on CPU (CTranslate2 does not support MPS).")
    speak("Systems loaded. Running Whisper on CPU.")

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

    speech_threshold, amb_mean, amb_max = calibrate_mic(audio_interface)
    print(f"[JARVIS] Mic calibrated — ambient mean={amb_mean:.0f}, peak={amb_max:.0f} → speech threshold={speech_threshold}")
    speak(f"Calibration complete. Speech threshold set to {speech_threshold}.")

    print("[JARVIS] All systems online. Listening.")

    # -- MEMORY SYSTEM INIT --
    print("[JARVIS] Initializing memory system...")
    global SYSTEM_PROMPT
    try:
        from memory.memory_manager import MemoryManager
        memory = MemoryManager(
            jarvis_root=JARVIS_ROOT,
            ollama_url=OLLAMA_URL,
            ollama_model=OLLAMA_MODEL,
            embedding_model=MEMORY_EMBEDDING_MODEL,
            decay_tau_days=MEMORY_DECAY_TAU,
            context_budget_tokens=MEMORY_CONTEXT_BUDGET,
        )
        
        # Bake stable identity into system prompt for massive KV cache reuse
        stable_mem = memory.get_stable_context()
        if stable_mem:
            SYSTEM_PROMPT += "\n\n" + stable_mem
            
    except Exception as e:
        print(f"[JARVIS] Warning: Memory system failed to initialize ({e}).")
        print("[JARVIS] Continuing without persistent memory.")
        memory = None

    print("[JARVIS] Initializing Semantic Router...")
    if memory:
        semantic_router = SemanticRouter(JARVIS_TOOLS, memory)
    else:
        print("[JARVIS] Semantic Router disabled (Memory required for embeddings).")
        semantic_router = None

    # -- RUNTIME STATE (JARVIS self-awareness) --
    jarvis_state = {
        "whisper_device": whisper_device,
        "whisper_model": WHISPER_MODEL,
        "llm_model": OLLAMA_MODEL,
        "llm_backend": "Ollama (local)",
        "tts_engine": "Piper",
        "tts_voice": f"{PIPER_VOICE} (EN) / {PIPER_VOICE_HINDI} (HI)",
        "mic_threshold": speech_threshold,
        "start_time": datetime.now(),
        "language_mode": "english",
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

    try:
        while True:
            # Wait for any previous speech to finish before listening
            wait_for_speech()

            # -- LISTEN --
            frames = listen(audio_interface, speech_threshold, vad_model)
            if frames is None:
                continue

            # -- TRANSCRIBE --
            try:
                # Force whisper language if we are in locked mode to improve accuracy and speed
                lang = WHISPER_LANGUAGE
                if jarvis_state.get("language_mode") == "hindi":
                    lang = "hi"
                elif jarvis_state.get("language_mode") == "english":
                    lang = "en"
                
                text, detected_lang = transcribe(model, frames, audio_interface, lang)
            except Exception as e:
                print(f"[JARVIS] Transcription error: {e}")
                continue

            if text is None:
                continue

            # -- WAKE WORD CHECK (via Whisper transcript) --
            clean_text = text.lower().replace('.', '').replace(',', '').replace('!', '').replace('?', '').replace('-', '').strip()

            # 100% Bulletproof Wake Word Check using actual text
            if not any(w in clean_text for w in ["jarvis", "जार्विस", "जारविस", "जारvis"]):
                continue

            # -- CASE: Just the wake word (user paused, waiting to give command) --
            from config.config import WAKE_WORDS
            if clean_text in WAKE_WORDS:
                print(f"\n[You]    {text}")
                speak("Yes sir?")
                wait_for_speech()
                
                # Setup background transcriber for the actual command
                cmd_lang = WHISPER_LANGUAGE
                if jarvis_state.get("language_mode") == "hindi":
                    cmd_lang = "hi"
                elif jarvis_state.get("language_mode") == "english":
                    cmd_lang = "en"
                    
                transcriber = BackgroundTranscriber(model, audio_interface, cmd_lang)
                transcriber.start()

                # Listen again for the actual command
                print("[JARVIS] Listening for command...")
                frames = listen(audio_interface, speech_threshold, vad_model, transcriber)
                
                if frames is None:
                    transcriber.stop_and_get([])  # stop the thread
                    continue
                
                try:
                    text, detected_lang = transcriber.stop_and_get(frames)
                except Exception as e:
                    print(f"[JARVIS] Transcription error: {e}")
                    continue
                
                if text is None:
                    continue

            print(f"\n[You]    {text}")

            # -- Language Mode Overrides --
            clean_cmd = text.lower().replace('.', '').replace(',', '').replace('!', '').replace('?', '').strip()
            
            hindi_triggers = ["talk in hindi", "speak in hindi", "switch to hindi", "hindi mode", "talkin hindi", "talkin hindee", "talk to me in hindi"]
            english_triggers = ["talk in english", "speak in english", "switch to english", "english mode", "talkin english", "talk to me in english"]

            if any(t in clean_cmd for t in hindi_triggers):
                jarvis_state["language_mode"] = "hindi"
                print("[JARVIS] Language mode locked to: HINDI")
                speak("Switched to Hindi mode sir.")
            elif any(t in clean_cmd for t in english_triggers):
                jarvis_state["language_mode"] = "english"
                print("[JARVIS] Language mode locked to: ENGLISH")
                speak("Switched to English mode sir.")

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

            # -- SEMANTIC ROUTING --
            tools_to_pass = None
            query_embedding = None
            if semantic_router:
                routing_query = text.lower()
                from config.config import WAKE_WORDS
                for w in WAKE_WORDS:
                    if w in routing_query:
                        routing_query = routing_query.replace(w, "").strip()
                if not routing_query:
                    routing_query = text
                
                # Compute embedding once
                query_embedding_np = semantic_router.embedder.encode([routing_query], normalize_embeddings=True)[0]
                query_embedding = query_embedding_np.tolist()
                
                tools_to_pass = semantic_router.route(routing_query, query_embedding=query_embedding_np)

            # -- BUILD DYNAMIC CONTEXT --
            live_context = build_live_context(jarvis_state)
            
            # Skip dynamic memory for confident single-tool commands
            is_direct_command = tools_to_pass and len(tools_to_pass) == 1
            if memory and not is_direct_command:
                try:
                    dynamic_mem = memory.get_dynamic_context(text, query_embedding=query_embedding)
                    if dynamic_mem:
                        live_context += "\n\n" + dynamic_mem
                except Exception as e:
                    print(f"[JARVIS] Dynamic memory context error: {e}")

            # -- THINK & SPEAK --
            try:
                response = think_and_speak(history, text, live_context, tools_to_pass=tools_to_pass)
            except requests.exceptions.ConnectionError:
                print("[JARVIS] Ollama is not running. Please start Ollama and try again.")
                speak("Ollama is not running sir. Please start it.")
                continue
            except Exception as e:
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
        _global_text_q.join()
        _global_audio_q.join()
    finally:
        audio_interface.terminate()


if __name__ == "__main__":
    main()
