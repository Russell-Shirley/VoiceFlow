# VoiceFlow — Product Requirements Document (Revised)

## Voice-to-Text Dictation with AI Polish for Windows + Hermes Agent Integration

**Status:** Approved Architecture — Moving to PoC Phase  
**Author:** Russell Shirley, Stan (System Architect)  
**Last Updated:** May 28, 2026  
**Version:** 4 — Post-architecture-review revision

---

## Revision Summary (v3 → v4)

This revision closes all open questions for PoC scope and resolves implementation gaps identified during final architecture review.

**Decisions locked:**
1. LLM cleanup uses a provider-abstracted layer via OpenRouter. No hard-wired model — the runbook builder selects the cheapest model that reliably handles grammar/punctuation at build time.
2. Daemon packaging is a manually launched tray process. No auto-start with Windows.
3. Config location is bundled next to binaries in the release folder.

**Gaps closed:**
- Committed to lock-file signaling for PoC (socket/pipe deferred to hardening phase)
- Added focus-safety implementation to AHK code
- Added startup handshake to prevent race condition on slow hardware
- Added max recording duration (90 seconds)
- Added retry/timeout spec for cloud calls
- Added user-facing error feedback via system tray notification
- Updated cost table to reflect provider-abstracted model selection
- Added clipboard retry logic notation

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
- No GUI or system tray UI (system-tray background runner is fine)
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
| AI text cleanup (Grammar) | **Cloud (OpenRouter)** | Provider-abstracted cleanup layer; cheapest viable model selected at build time |
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

Before any paste action, the runtime must verify that the foreground window matches the window captured at recording start. If focus has changed, the system must not inject blindly; it should leave the result on the clipboard and display a tray notification warning the user that focus changed. See Section 6.2 for implementation.

### 3.3 Cloud Latency & Reliability

The pipeline has three network hops (mic upload → Whisper API → OpenRouter API → response). Acceptable latency is under 3 seconds total. Cloud APIs introduce dependency on internet connectivity — mitigated by the hardening roadmap (Section 7.4).

**Retry and timeout spec (PoC):**
- Per-request timeout: 10 seconds
- Retry count: 1 retry per cloud call (Whisper and LLM independently)
- Backoff: 500ms before retry
- Total pipeline timeout: 25 seconds (hard ceiling, enforced by AHK `ClipWait`)
- On total failure: tray notification "VoiceFlow: transcription failed — check connection"

### 3.4 Clipboard History Preservation

AHK must backup and restore the user's clipboard before/after injection. Clipboard operations (`OpenClipboard`) must be wrapped in retry logic (up to 3 attempts, 50ms apart) because another process may hold the clipboard lock. This is handled by the pre-flight memoization sequence in the AHK wrapper (Section 6.2).

### 3.5 Cherry Audio Passthrough

The system must respect the default Windows input device and work with any audio source (Bluetooth headset, webcam mic, dedicated USB mic).

### 3.6 Max Recording Duration

Recording is capped at 90 seconds. If the user holds the hotkey beyond 90 seconds, the daemon auto-stops recording and proceeds with the captured audio. This prevents unbounded temp file growth and avoids exceeding Whisper API's 25MB file limit (90 seconds at 16kHz mono 16-bit ≈ 2.7MB, well within limits).

### 3.7 Observability Requirement

The system must expose state transitions and failure reasons for recording, uploading, transcription, cleanup, injection, retry, and timeout. Silent failure is not acceptable. Without this, troubleshooting will be guesswork and the support burden will be high.

**User-facing error feedback (PoC):** Windows system tray balloon notifications for all failure states. Messages should be short and actionable (e.g., "VoiceFlow: no audio detected", "VoiceFlow: transcription failed — check connection", "VoiceFlow: focus changed — text on clipboard").

---

## 4. Evaluated Solutions

### Solution A: Full Windows Agent with Local WSL Backend (Original Recommendation)

A small Windows-native service that handles the frontend (hotkey + mic + injection) and delegates AI work to WSL Ollama.

**Pros:** Full control, fully local, integrates with existing Ollama stack  
**Cons:** Requires WSL + Ollama running on LAN; edge devices must be able to reach the WSL host; local Whisper still taxes older CPUs

**Status:** Deferred to post-PoC hardening phase (see Section 7.4 — `hermes_lan` mode)

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

**PoC signaling model:** Lock-file based (AHK writes/deletes a lock file; daemon polls for it). Socket/pipe signaling is deferred to the hardening phase.

**Startup model:** User manually launches `VoiceFlow.exe`, which starts the tray process. No Windows auto-start registration.

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
│       │        │  - 90s max recording cap │              │
│       │        └────────────┬────────────┘              │
│       │                     │                            │
│  [Ctrl+Space Up] ────► Lock file delete                  │
│       │              (stop recording signal)             │
│       ▼                                                  │
└────────────────────────────┼────────────────────────────┘
                             │
                             ▼ (HTTPS via Public Internet)
┌─────────────────────────────────────────────────────────┐
│ Cloud Processing Layer (Provider-Abstracted)            │
│                                                         │
│  1. STT API (whisper-1 for PoC)  ──► Audio-to-Text      │
│  2. LLM Post-Processing Layer    ──► Grammar/Filler Fix │
│     (OpenRouter, cheapest viable model at build time)    │
│     (No hard-wired model string in code)                │
└────────────────────────────┼────────────────────────────┘
                             │
                             ▼ (Clean Text Response)
┌─────────────────────────────────────────────────────────┐
│ Windows Edge Device (Injection Sequence)                │
│                                                         │
│  1. Focus verification (window HWND match check)        │
│  2. Python writes response to Win32 Native Clipboard     │
│     (with retry: up to 3 attempts, 50ms apart)          │
│  3. AHK fires Universal Paste (Ctrl+V)                  │
│  4. Active Field Populated ◄── Historical Clipboard Restored
│                                                         │
│  On focus mismatch: skip paste, leave text on clipboard, │
│  show tray notification                                  │
└─────────────────────────────────────────────────────────┘
```

### Architectural Component Breakdown

| Component | Responsibility | Technical Selection | Rationale |
|-----------|---------------|-------------------|-----------|
| **Global Hooking** | System-tray listener capturing immediate key states | AutoHotkey (AHK) | Low-level `WH_KEYBOARD_LL` hooks avoid Windows Defender flags and eliminate Python GIL latency |
| **Audio Stream** | Capturing microphone data to temporary memory buffers | Python + `sounddevice` | Bundles PortAudio binaries natively, eliminating compilation friction on old Windows setups; natively streams into ML-ready formats |
| **Transcription** | Converting raw speech file into a raw text string | Cloud STT API — `whisper-1` (OpenAI) for PoC, provider-abstracted | Completely bypasses CPU-bound local transcription loops that choke older dual-core processors |
| **AI Editing** | Stripping filler words and applying grammar/punctuation adjustments | Provider-abstracted LLM layer via OpenRouter — cheapest viable model selected at build time | Grammar/punctuation cleanup is a narrow formatting task; does not require a frontier model |
| **UI Injection** | Dropping text cleanly into target applications | AHK Universal Paste (Ctrl+V) — clipboard-based injection is the **PoC implementation**; leaves room for Unicode input or UIA fallback in hardening phase | Battle-tested universal compatibility |

---

## 6. Technical Specifications & Implementation Code

### Process Model: Persistent Daemon with AHK Hotkey Shim (PoC)

The PoC uses a **lock-file signaling** model between AHK and the Python daemon. This is simpler to implement and debug, with socket/pipe signaling deferred to the hardening phase.

1. **AHK** captures key events. On key-down, it writes a lock file and sends a start signal. On key-up, it deletes the lock file.
2. **Persistent Python daemon** (manually launched tray process) polls for the lock file, owns session lifecycle, audio capture, cloud handoff (with retry/timeout), injection safety, and cleanup.
3. The daemon logs all state transitions for observability and surfaces errors via tray notifications.

**Startup sequence:**
1. User runs `VoiceFlow.exe` (compiled AHK).
2. AHK checks if `voiceflow_daemon.exe` is already running. If not, spawns it with `Run, voiceflow_daemon.exe,, Hide`.
3. Daemon writes a ready signal file (`voiceflow_ready.lock`) when initialized.
4. AHK waits up to 5 seconds for the ready signal before enabling hotkey listener.
5. If daemon fails to start, AHK shows a tray notification and exits.

### 6.1 The Edge Processing Pipeline (`voiceflow_daemon.py`)

This standalone script handles the audio recording, temporary storage, cloud handoffs, and native Win32 clipboard injection.

```python
import os
import sys
import time
import wave
import sounddevice as sd
import numpy as np
import requests
import ctypes
import json
import logging

# ── Constants ──
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORDING_SECONDS = 90
LOCK_FILE_FLAG = os.path.join(os.environ.get('TEMP', ''), 'voiceflow_recording.lock')
READY_FILE_FLAG = os.path.join(os.environ.get('TEMP', ''), 'voiceflow_ready.lock')
WAV_PATH = os.path.join(os.environ.get('TEMP', ''), 'voiceflow_temp.wav')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'voiceflow.log')
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config.json')

# ── Cloud retry/timeout constants ──
REQUEST_TIMEOUT = 10       # seconds per cloud request
MAX_RETRIES = 1            # one retry per cloud call
RETRY_BACKOFF = 0.5        # seconds between retries
CLIPBOARD_RETRIES = 3      # clipboard open attempts
CLIPBOARD_RETRY_DELAY = 0.05  # seconds between clipboard retries

# ── Logging ──
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger('voiceflow')

# ── Config ──
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

config = load_config()
OPENAI_API_KEY = config["openai_api_key"]       # Move to Credential Manager for production
OPENROUTER_API_KEY = config["openrouter_api_key"] # Move to Credential Manager for production
OPENROUTER_MODEL = config.get("openrouter_model", "")  # Selected at build time for cheapest viable

# ── Tray notification (Win32) ──
def show_tray_notification(title, message):
    """Display a Windows system tray balloon notification."""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=5, threaded=True)
    except Exception as e:
        log.warning(f"Tray notification failed: {e}")

def record_audio():
    log.info("Recording started")
    audio_data = []
    max_chunks = int((MAX_RECORDING_SECONDS * SAMPLE_RATE) / 1024)
    chunk_count = 0
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16') as stream:
        while os.path.exists(LOCK_FILE_FLAG) and chunk_count < max_chunks:
            chunk, _ = stream.read(1024)
            audio_data.append(chunk)
            chunk_count += 1
            time.sleep(0.01)
    if chunk_count >= max_chunks:
        log.info("Max recording duration reached (90s)")
    log.info(f"Recording stopped: {chunk_count * 1024 / SAMPLE_RATE:.1f}s captured")
    if not audio_data:
        return None
    return np.concatenate(audio_data, axis=0)

def save_wav(data):
    with wave.open(WAV_PATH, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data.tobytes())

def cloud_request_with_retry(method, url, retries=MAX_RETRIES, **kwargs):
    """Generic cloud request with timeout and retry."""
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)
    last_error = None
    for attempt in range(1 + retries):
        try:
            response = method(url, **kwargs)
            if response.status_code == 200:
                return response
            last_error = f"HTTP {response.status_code}"
            log.warning(f"Cloud call failed (attempt {attempt+1}): {last_error}")
        except requests.exceptions.Timeout:
            last_error = "timeout"
            log.warning(f"Cloud call timed out (attempt {attempt+1})")
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            log.warning(f"Cloud call error (attempt {attempt+1}): {last_error}")
        if attempt < retries:
            time.sleep(RETRY_BACKOFF)
    return None

def process_cloud_pipeline():
    if not os.path.exists(WAV_PATH):
        log.error("No WAV file found")
        return None

    # Step 1: Cloud Transcription
    log.info("Uploading to Whisper API")
    whisper_url = "https://api.openai.com/v1/audio/transcriptions"
    whisper_headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    with open(WAV_PATH, "rb") as f:
        files = {
            "file": (os.path.basename(WAV_PATH), f, "audio/wav"),
            "model": (None, "whisper-1")
        }
        response = cloud_request_with_retry(
            requests.post, whisper_url,
            headers=whisper_headers, files=files
        )

    if response is None:
        log.error("Whisper API failed after retries")
        show_tray_notification("VoiceFlow", "Transcription failed — check connection")
        return None

    raw_text = response.json().get("text", "")
    if not raw_text.strip():
        log.warning("Whisper returned empty text")
        show_tray_notification("VoiceFlow", "No speech detected")
        return None

    log.info(f"Raw transcription: {len(raw_text)} chars")

    # Step 2: AI Polish Layer (provider-abstracted)
    log.info("Sending to LLM cleanup")
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

    or_response = cloud_request_with_retry(
        requests.post, openrouter_url,
        headers=or_headers, json=payload
    )

    if or_response is None:
        log.error("LLM cleanup failed after retries — falling back to raw transcription")
        show_tray_notification("VoiceFlow", "Cleanup failed — using raw transcription")
        return raw_text  # Graceful degradation: return unpolished text

    polished = or_response.json()["choices"][0]["message"]["content"].strip()
    log.info(f"Polished text: {len(polished)} chars")
    return polished

def set_clipboard_text(text):
    """Win32 API clipboard write with retry logic."""
    for attempt in range(CLIPBOARD_RETRIES):
        result = ctypes.windll.user32.OpenClipboard(None)
        if result:
            ctypes.windll.user32.EmptyClipboard()
            h_global_mem = ctypes.windll.kernel32.GlobalAlloc(
                0x0042, len(text.encode('utf-16-le')) + 2
            )
            p_global_mem = ctypes.windll.kernel32.GlobalLock(h_global_mem)
            ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(p_global_mem), text)
            ctypes.windll.kernel32.GlobalUnlock(h_global_mem)
            ctypes.windll.user32.SetClipboardData(13, h_global_mem)
            ctypes.windll.user32.CloseClipboard()
            return True
        log.warning(f"Clipboard locked (attempt {attempt+1})")
        time.sleep(CLIPBOARD_RETRY_DELAY)
    log.error("Failed to open clipboard after retries")
    show_tray_notification("VoiceFlow", "Clipboard busy — text not injected")
    return False

def signal_ready():
    """Write ready file so AHK knows the daemon is initialized."""
    with open(READY_FILE_FLAG, 'w') as f:
        f.write("ready")
    log.info("Daemon ready signal written")

def cleanup():
    if os.path.exists(WAV_PATH):
        os.remove(WAV_PATH)

if __name__ == "__main__":
    log.info("Daemon starting")
    signal_ready()

    # Main loop: wait for recording lock file, process, repeat
    try:
        while True:
            # Wait for AHK to create the lock file (recording start)
            while not os.path.exists(LOCK_FILE_FLAG):
                time.sleep(0.05)

            raw_audio = record_audio()
            if raw_audio is None:
                log.warning("No audio captured")
                show_tray_notification("VoiceFlow", "No audio detected")
                cleanup()
                continue

            save_wav(raw_audio)
            polished_text = process_cloud_pipeline()

            if polished_text:
                set_clipboard_text(polished_text)

            cleanup()
    except KeyboardInterrupt:
        log.info("Daemon shutting down")
        if os.path.exists(READY_FILE_FLAG):
            os.remove(READY_FILE_FLAG)
```

### 6.2 The Native Wrapper Trigger (`VoiceFlow.ahk`)

This script manages the user's push-to-talk interaction loop, ensures daemon readiness, captures the active window for focus-safety, backs up clipboard data, and manages text injection.

```autohotkey
#NoEnv
SendMode Input
SetWorkingDir %A_ScriptDir%

; ── Startup: Ensure daemon is running ──
ReadyFile := A_Temp . "\voiceflow_ready.lock"
LockFile := A_Temp . "\voiceflow_recording.lock"

; Check if daemon is already running
Process, Exist, voiceflow_daemon.exe
if (!ErrorLevel) {
    Run, voiceflow_daemon.exe,, Hide
}

; Wait for daemon ready signal (up to 5 seconds)
StartWait := A_TickCount
Loop {
    if (FileExist(ReadyFile))
        break
    if (A_TickCount - StartWait > 5000) {
        TrayTip, VoiceFlow, Daemon failed to start — exiting., 5, 3
        Sleep, 3000
        ExitApp
    }
    Sleep, 100
}

TrayTip, VoiceFlow, Ready — hold Ctrl+Space to dictate., 3, 1

; ── Push-To-Talk Execution Route ──
^Space::
    ; 1. Capture active window HWND for focus-safety check
    WinGet, OrigHwnd, ID, A

    ; 2. Pre-Flight Memoization Sequence: Backup clipboard
    ClipSaved := ClipboardAll
    Clipboard := ""

    ; 3. Signal recording start
    FileAppend, active, %LockFile%

    ; 4. Maintain blocking lock state while user holds key sequence
    KeyWait, Space

    ; 5. Signal recording complete
    FileDelete, %LockFile%

    ; 6. Await data pipeline resolution (25-second safety timeout)
    ClipWait, 25
    if (!ErrorLevel) {
        ; 7. Focus-safety check: verify window hasn't changed
        WinGet, CurrentHwnd, ID, A
        if (CurrentHwnd = OrigHwnd) {
            ; Universal injection into target window field
            Send, ^v
            Sleep, 150
        } else {
            ; Focus changed — leave text on clipboard, warn user
            TrayTip, VoiceFlow, Focus changed — text left on clipboard., 5, 2
        }
    } else {
        ; Timeout — pipeline failed
        TrayTip, VoiceFlow, Transcription timed out., 5, 3
    }

    ; 8. Restore the user's historical clipboard history
    ;    (only if paste succeeded; if focus changed, user may want to paste manually)
    WinGet, CheckHwnd, ID, A
    if (CurrentHwnd = OrigHwnd) {
        Clipboard := ClipSaved
    }
    ClipSaved := ""
return
```

### 6.3 Configuration File (`config.json`)

Bundled next to binaries in the release folder.

```json
{
    "openai_api_key": "YOUR_OPENAI_API_KEY",
    "openrouter_api_key": "YOUR_OPENROUTER_API_KEY",
    "openrouter_model": "",
    "mode": "cloud_direct"
}
```

**Note:** `openrouter_model` is intentionally blank. The runbook builder sets this to the cheapest viable model on OpenRouter that passes the grammar/punctuation test suite at build time. This value is not hard-coded into the source.

### 6.4 Agent Mode (Future)

For Hermes agent interaction, a second hotkey (`^+Space` / Ctrl+Shift+Space) will follow the same pipeline but route the cleaned text to the Hermes Slack gateway or `hermes run` CLI instead of clipboard injection. Implementation deferred to post-PoC.

---

## 7. Operational Deployment & Packaging Strategy

To keep rollout frictionless across the distributed tester fleet, the toolset will be frozen into zero-dependency standalone binaries.

### 7.1 Credential Security

API credentials are stored in `config.json` bundled with the release binaries for PoC. Production hardening should migrate to Windows Credential Manager or DPAPI-protected local storage. Plaintext key placeholders are only acceptable in sample code. The system must also define a retention policy for raw audio, transcripts, and logs.

### 7.2 Freezing Environment Execution

On a standard Windows development machine, compile the Python pipeline using PyInstaller with the `--noconsole` flag to suppress command prompt flickering on older machines.

```bash
pip install pyinstaller sounddevice numpy requests win10toast
pyinstaller --noconsole --onefile voiceflow_daemon.py
```

### 7.3 Binary Compilation & Distribution Package

1. Run the native AutoHotkey compiler (`Ahk2Exe.exe`) against `VoiceFlow.ahk` to output a compiled executable: `VoiceFlow.exe`.
2. Bundle the resulting artifacts into a flat distribution directory:

```
VoiceFlow-Release/
├── VoiceFlow.exe               (The main hotkey listener + tray launcher)
├── voiceflow_daemon.exe         (The persistent processing daemon)
├── config.json                  (User configuration — API keys + model selection)
└── voiceflow.log                (Created at runtime — observability log)
```

**Startup sequence:**
1. User extracts zip, edits `config.json` with their API keys.
2. User runs `VoiceFlow.exe`.
3. AHK spawns `voiceflow_daemon.exe` if not already running.
4. AHK waits for daemon ready signal (up to 5 seconds).
5. Tray notification confirms "Ready."
6. User holds Ctrl+Space to dictate.

No Python runtimes, external dependencies, or complex environment configurations are required at the client layer.

### 7.4 Hardening Roadmap (Post-PoC Phase)

Once the cloud-direct interaction layer achieves user adoption stability among testers, the following improvements are planned:

**Signaling upgrade:** Replace lock-file polling with named pipe or localhost socket for lower latency and elimination of filesystem race conditions.

**Credential upgrade:** Migrate from `config.json` plaintext to Windows Credential Manager.

**Mode switching:** The `mode` field in `config.json` allows switching between processing backends:

| Mode | Description | When to Use |
|------|-------------|-------------|
| `cloud_direct` | Current PoC configuration — OpenAI Whisper + OpenRouter via public internet | Default for fleet / when internet is available |
| `hermes_lan` | Proxies raw audio files directly to a FastAPI gateway running inside your home WSL stack (Ollama for transcription + editing) | When on home network; lower latency, no API costs |
| `pure_local` | Bakes local execution of `whisper.cpp` and `llama.cpp` directly onto high-performance host hardware | Fully offline; for machines with sufficient local resources |

### 7.5 Cost Estimate (Cloud-Direct Mode)

| Service | Pricing | Est. Cost per 1000 dictations (30s avg) |
|---------|---------|----------------------------------------|
| OpenAI Whisper API | $0.006 / minute | ~$3.00 |
| OpenRouter (cheapest viable model) | Varies — selected at build time | ~$0.01–$0.15 (estimated) |
| **Total** | | **~$3.01–$3.15 per 1000 uses** |

*Note: LLM cleanup cost depends on the model selected at build time. Grammar/punctuation cleanup uses minimal tokens (~100–200 per request), so even models priced at $0.10/million tokens will be negligible at this volume.*

---

## 8. Resolved Questions (PoC)

These questions were open in v3 and are now locked for PoC.

| # | Question | PoC Decision |
|---|----------|-------------|
| 1 | LLM cleanup provider | Provider-abstracted via OpenRouter. Cheapest viable model selected at build time. No hard-wired model string. |
| 2 | Daemon packaging | Manually launched tray process. No auto-start with Windows. |
| 3 | Config location | Bundled next to binaries in the release folder. |
| 4 | Agent mode timing | Deferred to post-PoC. Dictation reliability must be proven first. |
| 5 | Offline mode timing | Deferred to post-PoC hardening phase. |

---

## 9. Post-PoC Open Questions

These remain open and will be addressed after PoC validation.

1. **Audio callback mode** — Should `sounddevice` switch from polling to callback mode for lower-latency recording?
2. **Injection alternatives** — Should the hardening phase introduce Unicode input simulation or UIA as alternatives to clipboard paste?
3. **Retention policy** — What is the retention policy for raw audio, transcripts, and logs?
4. **Agent mode design** — Full spec for Hermes agent routing via second hotkey.

---

*PRD v4 — May 28, 2026 — Architecture: Windows thin client + persistent daemon + cloud ML. PoC build. All PoC decisions locked.*
