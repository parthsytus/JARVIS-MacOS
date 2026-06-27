# JARVIS MacOS 🤖🍏

**A fully offline, voice-activated AI assistant designed natively for Apple Silicon.**

JARVIS MacOS is a complete port of the original JARVIS Windows project, reimagined for M1/M2/M3/M4/M5 Macs. It features zero cloud dependencies, local LLM execution via Ollama, local speech-to-text, local text-to-speech, and a robust long-term memory system.

---

## 🌟 Key Features

- **🗣️ Wake Word Detection:** Listens passively for "Hey Jarvis" using `openwakeword`.
- **👂 Local Speech-to-Text:** Fast, accurate voice transcription using `faster-whisper`.
- **🧠 Local LLM:** Runs `Gemma4:12b` (or any model) locally via Ollama with full Apple Metal GPU acceleration.
- **🗣️ Local Text-to-Speech:** Real-time voice generation using `Piper TTS` (English voice).
- **💾 Long-Term Memory:** Persistent RAG memory using `ChromaDB`, `sentence-transformers`, and a multi-tiered memory architecture (Episodic, Semantic, Procedural).
- **💻 Native macOS Control:** Control your Mac's volume, brightness, windows, apps, clipboard, and file system natively via AppleScript (`osascript`) and Homebrew tools.
- **🎵 Spotify Integration:** Full voice control for Spotify playback.

---

## ⚡ Quick Start

```bash
git clone https://github.com/parthsytus/JARVIS-MacOS.git
cd JARVIS-MacOS
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

## 📖 Documentation

For complete installation instructions, hardware requirements, troubleshooting, and architectural details, please see the **[SETUP_GUIDE.md](SETUP_GUIDE.md)**.

---

### Why JARVIS MacOS?

JARVIS was built with a core philosophy: **Your data shouldn't leave your machine.** 
By leveraging the unified memory architecture of Apple Silicon, JARVIS achieves low-latency, conversational AI entirely offline. It thinks, hears, speaks, and remembers locally.
