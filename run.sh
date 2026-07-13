#!/bin/bash
cd "$(dirname "$0")"

# Auto-start Ollama if not already running
if ! pgrep -x "ollama" > /dev/null; then
    echo "[JARVIS] Starting Ollama server..."
    ollama serve    
    sleep 2
fi

echo "[JARVIS] Starting..."
venv/bin/python core/jarvis_core.py
