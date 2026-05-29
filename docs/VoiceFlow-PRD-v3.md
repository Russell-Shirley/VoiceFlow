# VoiceFlow — Product Requirements Document (Revised)

## Voice-to-Text Dictation with AI Polish for Windows + Hermes Agent Integration

**Status:** Approved Architecture — Moving to PoC Phase  
**Author:** Russell Shirley, Stan (System Architect)  
**Last Updated:** May 28, 2026

---

## 1. Executive Summary

**Product:** VoiceFlow  
**Core Premise:** Press a hotkey, speak naturally, get clean/professional text injected into the active Windows app field — no manual pasting, no app-switching, no typing.

Glaido ($20/mo) does this with a hotkey + LLM edit layer. We want the same capability for personal use, integrated with our Hermes agent stack, and deployable to a mixed hardware fleet including older machines.

**Architecture Decision:** Windows thin client with persistent local runtime and cloud ML services for PoC, with a clear migration path to LAN/local processing.

---

## 2. Goals

### Primary
- **Single-hotkey dictation**: Press and hold one key sequence → speak → grammatically clean text appears at the cursor in any Windows app (Slack, Chrome, VS Code, Outlook, Notion, Cursor, terminal, etc.)
- **AI polish**: Strip filler words (um, uh, like, you know), add proper punctuation and capitalization, fix minor grammar — without changing the speaker's voice or intent
- **Zero local ML footprint**: All heavy ML workloads (Whisper transcription, grammar editing) handled in the cloud. The edge device handles only audio capture and keystroke injection.
- **Works on 10-year-old fleet hardware**: No local RAM or CPU starvation from running LLMs or Whisper locally.

### Secondary
- **Agent mode**: Route transcribed text to a Hermes agent (Slack DM or CLI prompt) when the user wants to talk *to* the agent rather than dictate *into* a field
- **Two-hotkey switching**: Distinguish between "dictate into this field" and "send to agent" via different key combos
- **History & recall**: Log all transcriptions (raw + cleaned) for search, review, or Cognee ingestion

### Non-goals
- No GUI or system tray (system-tray background runner is fine)
- No real-time streaming character-by-character (record → process → deliver is acceptable latency)
- No voice commands or agent actions in v1

---

## 3. Challenges

### 3.1 Cross-System Architecture (The Core Problem)

| Component | Where it should run | Why |
|-----------|-------------------|-----|
| Hotkey listener | **Windows** | Global hotkeys must be captured from Windows — WSL can't see keyboard events when focus is in a Windows app |
| Microphone capture | **Windows** | WSL can access the mic, but latency and routing are worse. Windows has native audio APIs |
| Audio → text (Whisper) | **Cloud (OpenAI API)** | Completely bypasses CPU-bound local transcription loops that choke older dual-core processors |
| AI text cleanup (Grammar) | **Cloud (OpenRouter)** | Delivers sub-second completion at fractional cost without taxing edge machine memory |
| Keystroke injection | **Windows** | AHK Universal Paste (Ctrl+V) is the gold standard for bypassing Electron, Chrome, and elevated UAC input-blocking |
| Agent routing | **WSL (future)** | Hermes CLI + Slack gateway live in WSL. Deferred to post-PoC phase |

### 3.2 Keystroke Injection into Any Windows App

| Method | Pros | Cons |
|--------|------|------|
| `SendKeys` (.NET / PowerShell) | Built into Windows, simple API | Can't inject into elevated/UAC apps; unreliable in some modern apps (Chrome, Electron) |
| `InputSimulator` (C#) | More reliable than SendKeys | Requires .NET; Chrome blocks simulated input in some contexts |
| `UI Automation` | Can target specific UI elements | Complex, slow, app-dependent |
| **AutoHotkey** (Selected) | **Battle-tested, handles edge cases, can paste text directly. Low-level `WH_KEYBOARD_LL` hooks avoid Windows Defender flags and eliminate Python GIL latency** | Requires compiled exe or AHK runtime |
| `Clipboard + Ctrl+V` | Works universally in every app ever | Requires simulated Ctrl+V (AHK handles this) |

**Verdict:** AutoHotkey for global hooking and universal paste. Low-level keyboard hooks eliminate Python GIL latency and avoid Windows Defender flags.

### 3.2a Focus-Safety Requirement

Before any paste action, the runtime must verify that the foreground window matches the window captured at recording start. If focus has changed, the system must not inject blindly; it should either leave the result on the clipboard or present a visible warning. This is a real-world failure mode that will happen, especially when users alt-tab or switch apps while waiting for the response.

### 3.3 Cloud Latency & Reliability

The pipeline now has three network hops (mic upload → Whisper API → OpenRouter API → response). Acceptable latency is under 3 seconds total. Cloud APIs introduce dependency on internet connectivity — mitigated by the hardening roadmap (Section 7.3).

### 3.4 Clipboard History Preservation

AHK must backup and restore the user's clipboard before/after injection. This is handled by the pre-flight memoization sequence in the AHK wrapper (Section 6.2).

### 3.5 Cherry Audio Passthrough

The system must respect the default Windows input device and work with any audio source (Bluetooth headset, webcam mic, dedicated USB mic).

### 3.6 Observability Requirement

The system must expose state transitions and failure reasons for recording, uploading, transcription, cleanup, injection, retry, and timeout. Silent failure is not acceptable. Without this, troubleshooting will be guesswork and the support burden will be high.

---

## 4. Evaluated Solutions

### Solution A: Full Windows Agent with Local WSL Backend (Original Recommendation)

A small Windows-native service that handles the frontend (hotkey + mic + injection) and delegates AI work to WSL Ollama.

**Pros:** Full control, fully local, integrates with existing Ollama stack  
**Cons:** Requires WSL + Ollama running on LAN; edge devices must be able to reach the WSL host; local Whisper still taxes older CPUs

**Status:** Deferred to post-PoC hardening phase (see Section 7.3 — `hermes_lan` mode)

### Solution B: Minimal Wraparound of VoiceFlow WSL

Keep the WSL VoiceFlow prototype, add a thin Windows AHK shim that calls `wsl.exe voiceflow once` on hotkey press.

**Pros:** No new code, leverages existing prototype  
**Cons:** WSL latency, audio routing through WSL is fragile, requires WSL on edge device

**Status:** Rejected for PoC — too much friction for fleet deployment

### Solution C: Windows Built-in Dictation + AI Overlay

Use Win+H for dictation, then route to cloud LLM for polish.

**Pros:** Zero Windows code, Windows dictation is decent  
**Cons:** Windows dictation online-only, extra step to invoke polish, not a unified experience

**Status:** Rejected for PoC — fragmented user experience

### Solution D: Full Windows Native (All Local)

Run everything on Windows (Whisper + Ollama for Windows).

**Pros:** No cross-system complexity  
**Cons:** Heavy local footprint, duplicates infrastructure, doesn't solve the old-hardware problem

**Status:** Rejected for PoC — defeats the thin-client goal

---

## 5. Approved Architecture: Windows Thin Client with Persistent Local Runtime

To resolve the core cross-system architecture friction and accommodate a 10-year-old machine fleet without causing local RAM or CPU starvation, we are deploying a **Windows thin client with persistent local runtime** that offloads all heavy ML workloads to the cloud (Whisper API + LLM post-processing behind a provider-abstracted interface) for the initial PoC. The client is not stateless — it requires a resident runtime for session management, injection safety, retries, and clipboard handling. Typical end-to-end latency is under 3 seconds for standard dictation, with visible progress states and graceful timeout handling. The architecture maintains a clear technical path to introduce LAN/local processing later.

```
┌─────────────────────────────────────────────────────────┐
│ Windows Edge Device (Persistent Local Runtime)          │
│                                                         │
│  [Ctrl+Space Down] ──► AHK Low-Level Hook               │
│       │                     │                           │
│       │        ┌────────────┴────────────┐              │
│       │        │ Persistent Python Daemon │              │
│       │        │  (tray process)          │              │
│       │        │  - session lifecycle     │              │
│       │        │  - audio capture         │              │
│       │        │  - cloud handoff + retry │              │
│       │        │  - injection + safety    │              │
│       │        │  - observability logging │              │
│       │        └────────────┬────────────┘              │
│       │                     │                            │
│  [Ctrl+Space Up] ────► Named pipe / localhost socket     │
│       │              (start/stop commands)               │
│       ▼                                                  │
└────────────────────────────┼────────────────────────────┘
                             │
                             ▼ (HTTPS via Public Internet)
┌─────────────────────────────────────────────────────────┐
│ Cloud Processing Layer (Provider-Abstracted)            │
│                                                         │
│  1. STT API (whisper-1 for PoC)  ──► Audio-to-Text      │
│  2. LLM Post-Processing Layer    ──► Grammar/Filler Fix │
│     (Multiple providers supported by contract)           │
└────────────────────────────┼────────────────────────────┘
                             │
                             ▼ (Clean Text Response)
┌─────────────────────────────────────────────────────────┐
│ Windows Edge Device (Injection Sequence)                │
│                                                         │
│  1. Focus verification (window match check)             │
│  2. Python writes response to Win32 Native Clipboard     │
│  3. AHK fires Universal Paste (Ctrl+V)                  │
│  4. Active Field Populated ◄── Historical Clipboard Restored
└─────────────────────────────────────────────────────────┘
```

### Architectural Component Breakdown

| Component | Responsibility | Technical Selection | Rationale |
|-----------|---------------|-------------------|-----------|
| **Global Hooking** | System-tray listener capturing immediate key states | AutoHotkey (AHK) | Low-level `WH_KEYBOARD_LL` hooks avoid Windows Defender flags and eliminate Python GIL latency |
| **Audio Stream** | Capturing microphone data to temporary memory buffers | Python + `sounddevice` | Bundles PortAudio binaries natively, eliminating compilation friction on old Windows setups; natively streams into ML-ready formats |
| **Transcription** | Converting raw speech file into a raw text string | Cloud STT API — `whisper-1` (OpenAI) for PoC, provider-abstracted | Completely bypasses CPU-bound local transcription loops that choke older dual-core processors |
| **AI Editing** | Stripping filler words and applying grammar/punctuation adjustments | LLM post-processing layer behind a provider-abstracted interface — Anthropic Claude 3 Haiku via OpenRouter for PoC | Delivers sub-second completion at a fractional cost without taxing edge machine memory |
| **UI Injection** | Dropping text cleanly into target applications | AHK Universal Paste (Ctrl+V) — clipboard-based injection is a **PoC fallback** and must be treated as a compatibility path, not the preferred long-term injection model | Leaves room for Unicode input or UIA fallback later |

---

## 6. Technical Specifications & Implementation Code

### Process Model: Persistent Daemon with AHK Hotkey Shim

Rather than spawning a new Python process on each hotkey press (which introduces race conditions and startup latency), the architecture uses a **persistent local daemon** pattern:

1. **AHK** captures key events and sends start/stop commands to the daemon over a named pipe or localhost socket.
2. **Persistent Python daemon** (tray process) owns session lifecycle, audio capture, cloud handoff (with retry), injection safety, and cleanup.
3. The daemon logs all state transitions for observability.

The code below illustrates the *processing logic* of the daemon. Packaging as a persistent service (rather than a spawned-on-demand exe) is expected for production.

### 6.1 The Edge Processing Pipeline (`voiceflow_daemon.py`)

This standalone script handles the audio recording, temporary storage, cloud handoffs, and native Win32 clipboard injection.

```python
import os
import time
import wave
import sounddevice as sd
import numpy as np
import requests
import ctypes

# Constants and System Paths
SAMPLE_RATE = 16000
CHANNELS = 1
# LOCK_FILE is replaced by named-pipe / socket commands in daemon mode
# Kept here for backwards compatibility with one-shot invocation
LOCK_FILE_FLAG = os.path.join(os.environ.get('TEMP', ''), 'voiceflow_recording.lock')
WAV_PATH = os.path.join(os.environ.get('TEMP', ''), 'voiceflow_temp.wav')

# API credentials loaded from Windows Credential Manager or config.json (Section 7.1)
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"  # Replace with Credential Manager read
OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY"  # Replace with Credential Manager read
OPENROUTER_MODEL = "anthropic/claude-3-haiku"  # Provider-abstraction layer TBD

def record_audio():
    audio_data = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16') as stream:
        while os.path.exists(LOCK_FILE_FLAG):
            chunk, _ = stream.read(1024)
            audio_data.append(chunk)
            time.sleep(0.01)  # Eliminate CPU spinning
    return np.concatenate(audio_data, axis=0)

def save_wav(data):
    with wave.open(WAV_PATH, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data.tobytes())

def process_cloud_pipeline():
    if not os.path.exists(WAV_PATH):
        return None

    # Step 1: Cloud Transcription
    whisper_url = "https://api.openai.com/v1/audio/transcriptions"
    whisper_headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    
    with open(WAV_PATH, "rb") as f:
        files = {
            "file": (os.path.basename(WAV_PATH), f, "audio/wav"),
            "model": (None, "whisper-1")
        }
        response = requests.post(whisper_url, headers=whisper_headers, files=files)
    
    if response.status_code != 200:
        return None
        
    raw_text = response.json().get("text", "")
    if not raw_text.strip():
        return None

    # Step 2: AI Polish Layer
    openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
    or_headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://voiceflow.internal"
    }
    
    system_prompt = (
        "You are a transcription formatting assistant. Clean up the text. "
        "Remove filler words (um, uh, like), fix grammar/punctuation. "
        "Do NOT change meaning or tone. Respond ONLY with the corrected text."
    )
    
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text}
        ]
    }
    
    or_response = requests.post(openrouter_url, headers=or_headers, json=payload)
    if or_response.status_code != 200:
        return None
        
    return or_response.json()["choices"][0]["message"]["content"].strip()

def set_clipboard_text(text):
    """Win32 API Native Injection to safely override clipboard text."""
    ctypes.windll.user32.OpenClipboard(None)
    ctypes.windll.user32.EmptyClipboard()
    h_global_mem = ctypes.windll.kernel32.GlobalAlloc(0x0042, len(text.encode('utf-16-le')) + 2)
    p_global_mem = ctypes.windll.kernel32.GlobalLock(h_global_mem)
    ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(p_global_mem), text)
    ctypes.windll.kernel32.GlobalUnlock(h_global_mem)
    ctypes.windll.user32.SetClipboardData(13, h_global_mem)
    ctypes.windll.user32.CloseClipboard()

if __name__ == "__main__":
    while not os.path.exists(LOCK_FILE_FLAG):
        time.sleep(0.05)
        
    raw_audio = record_audio()
    save_wav(raw_audio)
    
    polished_text = process_cloud_pipeline()
    if polished_text:
        set_clipboard_text(polished_text)
        
    if os.path.exists(WAV_PATH):
        os.remove(WAV_PATH)
```

### 6.2 The Native Wrapper Trigger (`VoiceFlow.ahk`)

This script executes the user's Push-To-Talk interaction loop, sends commands to the persistent daemon over a named pipe / localhost socket, backs up clipboard data, and manages text injection. The lock-file approach shown here is a PoC fallback — production uses socket-based commands.

```autohotkey
#NoEnv
SendMode Input
SetWorkingDir %A_ScriptDir%

; Push-To-Talk Execution Route
^Space::
    ; 1. Pre-Flight Memoization Sequence: Backup clipboard
    ClipSaved := ClipboardAll
    Clipboard := "" 
    
    ; 2. Daemon handoff via named pipe / localhost socket
    ;    (PoC fallback: lock file + spawned exe)
    FileAppend, active, %A_Temp%\voiceflow_recording.lock
    
    ; 3. Spawns the persistent daemon tray process
    ;    (or sends start command to already-running daemon)
    Run, voiceflow_daemon.exe,, Hide
    
    ; 4. Maintain blocking lock state while user holds key sequence
    KeyWait, Space
    
    ; 5. Signal recording complete
    FileDelete, %A_Temp%\voiceflow_recording.lock
    
    ; 6. Await data pipeline resolution (15-second safety timeout)
    ClipWait, 15
    if (!ErrorLevel) {
        ; Universal injection into target window field
        Send, ^v
        Sleep, 150 
    }
    
    ; 7. Restore the user's historical clipboard history
    Clipboard := ClipSaved
    ClipSaved := "" 
return
```

### 6.3 Agent Mode (Future)

For Hermes agent interaction, a second hotkey (`^+Space` / Ctrl+Shift+Space) will follow the same pipeline but route the cleaned text to the Hermes Slack gateway or `hermes run` CLI instead of clipboard injection. Implementation deferred to post-PoC.

---

## 7. Operational Deployment & Packaging Strategy

To keep rollout frictionless across the distributed tester fleet, the toolset will be frozen into zero-dependency standalone binaries.

### 7.1 Credential Security

API credentials must be stored in Windows Credential Manager or DPAPI-protected local storage. Plaintext key placeholders are only acceptable in sample code. The system must also define a retention policy for raw audio, transcripts, and logs.

### 7.2 Freezing Environment Execution

On a standard Windows development machine, compile the Python pipeline using PyInstaller with the `--noconsole` flag to suppress command prompt flickering on older machines.

```bash
pip install pyinstaller sounddevice numpy requests
pyinstaller --noconsole --onefile voiceflow_daemon.py
```

### 7.3 Binary Compilation & Distribution Package

1. Run the native AutoHotkey compiler (`Ahk2Exe.exe`) against `VoiceFlow.ahk` to output a compiled executable: `VoiceFlow.exe`.
2. Bundle the resulting artifacts into a flat distribution directory:

```
VoiceFlow-Release/
├── VoiceFlow.exe               (The main system-tray background runner)
└── voiceflow_edge_cloud.exe    (The silent processing pipeline binary)
```

**End-User Rollout:** Testers simply extract the zip file and execute `VoiceFlow.exe` once. No Python runtimes, external dependencies, or complex environment configurations are required at the client layer.

### 7.4 Hardening Roadmap (Post-PoC Phase)

Once the cloud-direct interaction layer achieves user adoption stability among testers, a local configuration pattern (`config.json`) will be implemented. This file allows users to dynamically switch the application's ingestion engine between three modes:

| Mode | Description | When to Use |
|------|-------------|-------------|
| `cloud_direct` | Current production configuration — OpenAI Whisper + OpenRouter via public internet | Default for fleet / when internet is available |
| `hermes_lan` | Proxies raw audio files directly to a FastAPI gateway running inside your home WSL stack (Ollama for transcription + editing) | When on home network; lower latency, no API costs |
| `pure_local` | Bakes local execution of `whisper.cpp` and `llama.cpp` directly onto high-performance host hardware | Fully offline; for machines with sufficient local resources |

### 7.5 Cost Estimate (Cloud-Direct Mode)

| Service | Pricing | Est. Cost per 1000 dictations (30s avg) |
|---------|---------|----------------------------------------|
| OpenAI Whisper API | $0.006 / minute | ~$3.00 |
| OpenRouter (Claude 3 Haiku) | ~$0.25 / million tokens | ~$0.10 |
| **Total** | | **~$3.10 per 1000 uses** |

---

## 8. Open Questions

1. **LLM cleanup provider** — Should cleanup use OpenAI, Anthropic, or a provider-abstracted backend selected by latency and cost benchmarking?
2. **Daemon packaging** — Should the local runtime be a Windows service, tray process, or resident daemon with AHK as a thin hotkey shim?
3. **`config.json` location** — Should it live in `%APPDATA%\VoiceFlow\config.json` rather than next to the binaries?
4. **Agent mode timing** — Should agent mode remain out of PoC and be added only after dictation reliability is proven?
5. **Offline mode timing** — Should offline mode (`pure_local`) remain deferred until after PoC?

---

*PRD v3 — May 28, 2026 — Architecture: Windows thin client + persistent daemon + cloud ML. PoC build.*
