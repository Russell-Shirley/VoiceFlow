# VoiceFlow

**Voice-to-text dictation with AI polish for Windows.**

Press a hotkey, speak naturally, get clean text injected into the active window — no pasting, no app-switching, no typing.

## How It Works

1. Hold `Ctrl+Space` and speak
2. Release — audio is sent to cloud for transcription (Whisper) and cleanup (LLM)
3. Polished text is pasted into the active window at the cursor

## Architecture

```
Windows (AHK hotkey + Python daemon) → Cloud (Whisper STT + LLM polish) → Clipboard paste
```

- **Thin client**: All ML runs in the cloud. Works on 10-year-old hardware.
- **Provider-abstracted**: LLM cleanup uses the cheapest viable model via OpenRouter.
- **Focus-safe**: Verifies the active window hasn't changed before pasting.

## Quick Start

1. Edit `config.json` with your API keys
2. Run `VoiceFlow.exe`
3. Wait for "Ready" tray notification
4. Hold `Ctrl+Space` to dictate

## Project Structure

```
VoiceFlow/
├── src/
│   ├── voiceflow_daemon.py     # Persistent Python daemon — audio, cloud, clipboard
│   └── VoiceFlow.ahk           # AHK hotkey listener + tray launcher
├── dist/                        # Build output (not tracked)
├── docs/
│   ├── VoiceFlow-PRD-v4.md     # Current PRD (approved)
│   └── VoiceFlow-PRD-v3.md     # Previous PRD (reference)
├── tests/                       # Test scripts
├── config.json.example          # Template config — copy to config.json
├── requirements.txt             # Python dependencies
├── build.bat                    # Build script for PyInstaller + AHK compilation
└── .gitignore
```

## Building

Requirements: Python 3.8+, PyInstaller, AutoHotkey v1.1+

```bash
# Install Python dependencies
pip install -r requirements.txt

# Build (Windows)
build.bat
```

Output lands in `dist/VoiceFlow-Release/`.

## Configuration

Copy `config.json.example` to `config.json` and fill in your API keys:

```json
{
    "openai_api_key": "sk-...",
    "openrouter_api_key": "sk-or-...",
    "openrouter_model": "select-at-build-time",
    "mode": "cloud_direct"
}
```

## Status

**PoC phase** — cloud-direct mode only. See [PRD v4](docs/VoiceFlow-PRD-v4.md) for full architecture and roadmap.

## License

Private — Bridge & Bolt internal use.
