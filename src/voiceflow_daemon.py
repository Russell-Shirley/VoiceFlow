"""
VoiceFlow Daemon — Persistent audio capture, cloud processing, and clipboard injection.

This daemon runs as a background tray process on Windows. It waits for the AHK
hotkey shim to signal recording start/stop via lock files, captures audio,
sends it to cloud APIs for transcription and cleanup, and writes the result
to the clipboard for AHK to paste.

See docs/VoiceFlow-PRD-v4.md for full architecture documentation.
"""

import os
import sys
import time
import wave
import json
import logging

import sounddevice as sd
import numpy as np
import requests
import ctypes

# ── Constants ──
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORDING_SECONDS = 90

TEMP_DIR = os.environ.get('TEMP', os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Temp'))
LOCK_FILE_FLAG = os.path.join(TEMP_DIR, 'voiceflow_recording.lock')
READY_FILE_FLAG = os.path.join(TEMP_DIR, 'voiceflow_ready.lock')
WAV_PATH = os.path.join(TEMP_DIR, 'voiceflow_temp.wav')

SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG_PATH = os.path.join(SCRIPT_DIR, 'voiceflow.log')
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')

# ── Cloud retry/timeout constants ──
REQUEST_TIMEOUT = 10          # seconds per cloud request
MAX_RETRIES = 1               # one retry per cloud call
RETRY_BACKOFF = 0.5           # seconds between retries
CLIPBOARD_RETRIES = 3         # clipboard open attempts
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
    """Load configuration from config.json next to the binary."""
    if not os.path.exists(CONFIG_PATH):
        log.error(f"Config file not found: {CONFIG_PATH}")
        print(f"ERROR: config.json not found at {CONFIG_PATH}")
        print("Copy config.json.example to config.json and add your API keys.")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


config = load_config()
OPENAI_API_KEY = config.get("openai_api_key", "")
OPENROUTER_API_KEY = config.get("openrouter_api_key", "")
OPENROUTER_MODEL = config.get("openrouter_model", "")

if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("YOUR_"):
    log.error("OpenAI API key not configured")
    print("ERROR: Set openai_api_key in config.json")
    sys.exit(1)

if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("YOUR_"):
    log.error("OpenRouter API key not configured")
    print("ERROR: Set openrouter_api_key in config.json")
    sys.exit(1)

if not OPENROUTER_MODEL:
    log.error("OpenRouter model not configured")
    print("ERROR: Set openrouter_model in config.json")
    sys.exit(1)


# ── Tray notification (Win32) ──
def show_tray_notification(title, message):
    """Display a Windows system tray balloon notification."""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=5, threaded=True)
    except Exception as e:
        log.warning(f"Tray notification failed: {e}")


# ── Audio ──
def record_audio():
    """Record audio while the lock file exists, up to MAX_RECORDING_SECONDS."""
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

    duration = chunk_count * 1024 / SAMPLE_RATE
    log.info(f"Recording stopped: {duration:.1f}s captured")

    if not audio_data:
        return None
    return np.concatenate(audio_data, axis=0)


def save_wav(data):
    """Write raw audio data to a temporary WAV file."""
    with wave.open(WAV_PATH, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data.tobytes())


# ── Cloud ──
def cloud_request_with_retry(method, url, retries=MAX_RETRIES, **kwargs):
    """Execute an HTTP request with timeout and retry logic."""
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)
    last_error = None

    for attempt in range(1 + retries):
        try:
            response = method(url, **kwargs)
            if response.status_code == 200:
                return response
            last_error = f"HTTP {response.status_code}"
            log.warning(f"Cloud call failed (attempt {attempt + 1}): {last_error}")
        except requests.exceptions.Timeout:
            last_error = "timeout"
            log.warning(f"Cloud call timed out (attempt {attempt + 1})")
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            log.warning(f"Cloud call error (attempt {attempt + 1}): {last_error}")

        if attempt < retries:
            time.sleep(RETRY_BACKOFF)

    return None


def process_cloud_pipeline():
    """Run the two-stage cloud pipeline: Whisper STT → LLM cleanup."""
    if not os.path.exists(WAV_PATH):
        log.error("No WAV file found")
        return None

    # Step 1: Cloud Transcription (Whisper)
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
        show_tray_notification("VoiceFlow", "Transcription failed \u2014 check connection")
        return None

    raw_text = response.json().get("text", "")
    if not raw_text.strip():
        log.warning("Whisper returned empty text")
        show_tray_notification("VoiceFlow", "No speech detected")
        return None

    log.info(f"Raw transcription: {len(raw_text)} chars")

    # Step 2: LLM Cleanup (provider-abstracted via OpenRouter)
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
        log.error("LLM cleanup failed after retries \u2014 falling back to raw transcription")
        show_tray_notification("VoiceFlow", "Cleanup failed \u2014 using raw transcription")
        return raw_text  # Graceful degradation

    polished = or_response.json()["choices"][0]["message"]["content"].strip()
    log.info(f"Polished text: {len(polished)} chars")
    return polished


# ── Clipboard ──
def set_clipboard_text(text):
    """Write text to Windows clipboard with retry logic for locked clipboard."""
    for attempt in range(CLIPBOARD_RETRIES):
        result = ctypes.windll.user32.OpenClipboard(None)
        if result:
            ctypes.windll.user32.EmptyClipboard()
            encoded = text.encode('utf-16-le')
            h_global_mem = ctypes.windll.kernel32.GlobalAlloc(0x0042, len(encoded) + 2)
            p_global_mem = ctypes.windll.kernel32.GlobalLock(h_global_mem)
            ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(p_global_mem), text)
            ctypes.windll.kernel32.GlobalUnlock(h_global_mem)
            ctypes.windll.user32.SetClipboardData(13, h_global_mem)
            ctypes.windll.user32.CloseClipboard()
            return True
        log.warning(f"Clipboard locked (attempt {attempt + 1})")
        time.sleep(CLIPBOARD_RETRY_DELAY)

    log.error("Failed to open clipboard after retries")
    show_tray_notification("VoiceFlow", "Clipboard busy \u2014 text not injected")
    return False


# ── Lifecycle ──
def signal_ready():
    """Write ready file so AHK knows the daemon is initialized."""
    with open(READY_FILE_FLAG, 'w') as f:
        f.write("ready")
    log.info("Daemon ready signal written")


def cleanup():
    """Remove temporary audio file."""
    if os.path.exists(WAV_PATH):
        os.remove(WAV_PATH)


# ── Main Loop ──
if __name__ == "__main__":
    log.info("Daemon starting")
    signal_ready()

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
