# AGENTS.md — Operating Rules for AI Engineers on VoiceFlow

> Vendor-neutral playbook for any AI coding agent — Claude Code, Cursor, Codex, Copilot, Cline, JetBrains AI, Aider, etc.
> If your tool reads `AGENTS.md`, read this end-to-end before touching code. If it reads `CLAUDE.md` or `.cursorrules`, treat that file as a pointer back here.

---

## 1. Project Identity

| | |
|---|---|
| **Product** | VoiceFlow — press a hotkey, speak naturally, get clean/professional text injected into the active Windows app field. No manual pasting, no app-switching, no typing. |
| **Owner** | Russell Shirley · Bridge and Bolt LLC (`russ.shirley@gmail.com`). |
| **Stack** | Python 3.8+ daemon (`sounddevice` + `numpy` + `requests` + `ctypes` Win32) → PyInstaller-frozen background process → AutoHotkey v1.1 hotkey shim + tray launcher. Cloud ML via OpenAI Whisper (STT) + OpenRouter (LLM cleanup, provider-abstracted). |
| **Deployment pattern** | **Windows Thin Client with Persistent Local Runtime.** User runs `VoiceFlow.exe` (compiled AHK), which silently spawns `voiceflow_daemon.exe` (frozen Python). AHK captures hotkeys, daemon handles audio/cloud/clipboard. All ML runs in the cloud — zero local ML footprint. End user never opens a terminal or sees Python. |
| **Status** | PoC phase — `cloud_direct` mode only. See [PRD v4](docs/VoiceFlow-PRD-v4.md) for full architecture and roadmap. |
| **Canonical architecture spec** | [`docs/VoiceFlow-PRD-v4.md`](docs/VoiceFlow-PRD-v4.md). Approved architecture, all PoC decisions locked. **Read it before architectural pushback.** |

---

## 2. Memory Layer (read at session start, in this order)

1. `AGENTS.md` (this file) — operating rules
2. `docs/VoiceFlow-PRD-v4.md` — approved architecture, locked decisions, hardening roadmap, cost model, full implementation code
3. `README.md` — project overview, quick start, structure
4. `docs/VoiceFlow-PRD-v3.md` — previous revision (reference only)

These files are the durable memory of the project. Decisions, rationale, and invariants live here — not in chat. If a memory file disagrees with code, the file is authoritative; reconcile by updating the file or the code, never silently.

---

## 3. North Star Invariants

These architectural rules are non-negotiable. Any change that violates one requires explicit user approval **and** a written rationale that updates the PRD.

1. **Zero local ML footprint.** All heavy ML workloads (Whisper transcription, LLM cleanup) run in the cloud. The edge device handles only audio capture and keystroke injection. This is non-negotiable for PoC — the product must work on 10-year-old fleet hardware without RAM or CPU starvation.

2. **Single-hotkey dictation must work in any Windows app.** Ctrl+Space → speak → polished text appears at the cursor. Slack, Chrome, VS Code, Outlook, Notion, Cursor, terminal, everything. AHK Universal Paste (Ctrl+V via clipboard) is the injection method. No exceptions for "certain apps don't work."

3. **Focus-safety is mandatory.** Before any paste action, verify the foreground window HWND matches the one captured at recording start. If focus changed: do NOT inject blindly, leave text on clipboard, show a tray notification. This prevents text being pasted into the wrong window.

4. **Clipboard history must be preserved.** AHK backs up `ClipboardAll` before recording and restores it after paste. Clipboard open/write operations use retry logic (up to 3 attempts, 50ms apart) because another process may hold the lock.

5. **Provider-abstracted LLM cleanup.** No hard-wired model string in code. The `openrouter_model` value in `config.json` is selected at build time for the cheapest viable model that reliably handles grammar/punctuation. Code must work with any model behind OpenRouter's chat completions API.

6. **Graceful degradation on LLM failure.** If the LLM cleanup stage fails after retries, fall back to raw Whisper transcription. The user gets unpolished text rather than nothing. Whisper failure (no transcription at all) is a hard stop with a tray notification.

7. **Lock-file signaling for PoC.** AHK writes/deletes a lock file in `%TEMP%`; daemon polls for it. Socket/pipe signaling is deferred to the hardening phase. Don't upgrade the signaling mechanism during PoC unless explicitly directed.

8. **90-second max recording duration.** If the user holds the hotkey beyond 90 seconds, the daemon auto-stops and processes what it has. This prevents unbounded temp file growth and stays within Whisper's 25MB limit.

9. **Every failure is visible.** Silent failure is not acceptable. All error states surface via Windows tray balloon notifications with short, actionable messages. All state transitions log to `voiceflow.log`.

10. **Config lives next to binaries.** `config.json` ships in the same folder as the executables. No registry entries, no AppData paths, no environment variables for PoC config. The release is a flat folder the user extracts and runs.

11. **No auto-start with Windows.** The daemon is a manually launched tray process. The user runs `VoiceFlow.exe` to start. No Task Scheduler entries, no startup folder shortcuts, no service registration.

12. **API keys are plaintext in `config.json` for PoC only.** Production hardening migrates to Windows Credential Manager or DPAPI. Never log API keys. Never embed keys in code or tests.

13. **Startup handshake prevents race conditions.** Daemon writes `voiceflow_ready.lock` when initialized. AHK waits up to 5 seconds for it before enabling the hotkey listener. If the daemon fails to start, AHK shows a tray notification and exits.

14. **Cloud retry and timeout spec is fixed for PoC.** Per-request timeout: 10s. Retry count: 1 per cloud call. Backoff: 500ms. Total pipeline timeout: 25s (enforced by AHK `ClipWait`). Don't change these without updating the PRD.

Before opening a PR, mentally walk this list.

---

## 4. Code Standards

### Python (daemon)

- **Python >= 3.8.** Target the oldest Python that PyInstaller supports well on Windows. No bleeding-edge syntax that breaks the frozen build.
- **No async.** The daemon is a synchronous polling loop. `time.sleep` for polling is fine here — there's no event loop to block. The daemon does one thing at a time: wait → record → upload → clipboard.
- **Use the module logger, not `print`.** `log = logging.getLogger('voiceflow')`. Log state transitions, durations, and error details. Logs go to `voiceflow.log` next to the binary.
- **Win32 clipboard via `ctypes`.** No pywin32 dependency. Direct `ctypes.windll.user32` / `ctypes.windll.kernel32` calls for clipboard operations. This keeps the frozen binary small.
- **Tray notifications via `win10toast`.** Short, actionable messages. If `win10toast` fails, log the failure and continue — never crash because a notification couldn't display.
- **No new top-level dependencies without justification.** Every pip dependency adds weight to the PyInstaller frozen binary and introduces a potential point of failure on fleet machines. The current deps are: `sounddevice`, `numpy`, `requests`, `win10toast`, `pyinstaller`.
- **Config loading fails fast.** If `config.json` is missing or API keys are placeholder values, exit immediately with a clear error message. Don't start the daemon in a broken state.
- **Temp files go in `%TEMP%`.** Lock files, ready signals, and temporary WAV files all live in the system temp directory. Clean up temp WAV files after every pipeline run.

### AutoHotkey (hotkey shim)

- **AutoHotkey v1.1 syntax.** Not v2. The compiled `.exe` targets AHK v1.1 — don't use v2-only constructs.
- **`#SingleInstance Force`** — only one copy of the hotkey listener runs.
- **All lock/ready file paths use `A_Temp`.** Must match the Python daemon's `%TEMP%` paths exactly.
- **Clean up stale lock files on startup.** Previous crashes may leave orphan lock files that would immediately trigger recording.
- **`KeyWait, Space`** for push-to-talk blocking. The hotkey is `^Space` (Ctrl+Space). Recording runs while the key is held; releasing stops it.
- **Clipboard backup/restore is AHK's responsibility.** Save `ClipboardAll` before recording, restore after paste (only if focus didn't change — user may want to manually paste if focus shifted).

### General

- **No comments that narrate what the code does.** Only comments that explain *why* something non-obvious is the way it is.
- **No features beyond what the task requires.** PoC scope is locked. Agent mode, offline mode, LAN mode, streaming — all deferred to post-PoC.
- **Format before commit.** Python: use a formatter (black/ruff if configured). AHK: consistent indentation.

---

## 5. Testing Standards

- **Tests live in `tests/`.** The test suite is planned but minimal for PoC.
- **Planned test categories** (see `tests/README.md`):
  1. **Cloud pipeline** — Mock Whisper and OpenRouter responses, verify retry/timeout behavior, verify graceful degradation on LLM failure
  2. **Clipboard** — Verify backup/restore, retry logic on locked clipboard, Unicode handling
  3. **Config** — Missing file, missing keys, placeholder key detection
  4. **Recording cap** — Verify 90-second enforcement
- **Mock all cloud calls in tests.** Never hit OpenAI or OpenRouter in automated tests. Use `unittest.mock` or `responses` to simulate API behavior.
- **Don't test trivial code paths.** If a test would never fail, don't write it.

---

## 6. Architecture Compliance Checks

When you touch any of the following areas, re-read the named PRD section and confirm your change preserves the contract:

| If you touch... | Re-read... |
|-----------------|------------|
| Audio recording (`record_audio`, `save_wav`) | PRD §3.5 Cherry Audio Passthrough, §3.6 Max Recording Duration |
| Cloud pipeline (`process_cloud_pipeline`, `cloud_request_with_retry`) | PRD §3.3 Cloud Latency & Reliability (retry/timeout spec) |
| Clipboard operations (`set_clipboard_text`) | PRD §3.4 Clipboard History Preservation |
| Focus-safety check (AHK HWND comparison) | PRD §3.2a Focus-Safety Requirement |
| Tray notifications (`show_tray_notification`) | PRD §3.7 Observability Requirement |
| Startup sequence (daemon launch, ready signal) | PRD §6 Process Model startup sequence |
| LLM system prompt or cleanup logic | PRD §5 Architecture table (AI Editing row) — must not change meaning or tone |
| `config.json` structure or loading | PRD §6.3 Configuration File, §7.1 Credential Security |
| Build script (`build.bat`) | PRD §7.2–7.3 Freezing & Distribution |
| Lock-file signaling paths | PRD §5 (PoC signaling model — lock-file based) |
| Hotkey binding (`^Space`) | PRD §2 Goals — single-hotkey dictation |

If a change can't be made without violating one of these, **stop and surface the conflict to the user before implementing.** The PRD has been through four revisions with architecture review — challenges are welcome but bear the burden of proof.

---

## 7. Task Execution Strategy

For every non-trivial task:

1. **Re-read the relevant memory files** (§2). Cite the PRD section that grounds your change.
2. **Plan minimal changes.** VoiceFlow has exactly two source files (`voiceflow_daemon.py` and `VoiceFlow.ahk`) plus config. If a change touches both files, verify the signaling contract (lock files, clipboard, ready signal) is preserved end-to-end.
3. **Implement step-by-step**, testing as you go.
4. **Update the PRD** if you made a decision worth preserving (a resolved post-PoC question, a new locked decision, a spec change). PRD changes require user approval.

For exploratory questions ("how should we approach X?"), respond in 2–3 sentences with a recommendation and the main trade-off. Don't implement until the user agrees.

---

## 8. Anti-Patterns (do not do these)

- **Adding local ML (Whisper, Ollama, llama.cpp) during PoC.** The entire point of the thin-client architecture is zero local ML. Local/LAN/offline modes are hardening-phase work (PRD §7.4).
- **Replacing lock-file signaling with sockets or pipes.** Lock-file polling is the PoC signaling model. Socket/pipe upgrade is deferred to hardening. Don't optimize prematurely.
- **Hard-coding an LLM model string.** The `openrouter_model` field is set at build time, not in source. Code must work with any model behind OpenRouter's API.
- **Pasting without focus-safety check.** Never inject text without verifying the foreground HWND matches the one captured at recording start. Blind injection into the wrong window is a data-loss risk.
- **Swallowing errors silently.** Every failure state must log AND show a tray notification. If you add a new failure path and forget the notification, the code is broken.
- **Adding a GUI or settings panel.** PoC scope is "system-tray background runner." No GUI beyond tray notifications.
- **Auto-starting with Windows.** Manual launch only. No services, no Task Scheduler, no startup folder registration.
- **Storing config in the registry, AppData, or environment variables.** Config is `config.json` next to the binaries. Flat folder, zero installation.
- **Using `pywin32` for clipboard or notifications.** The daemon uses `ctypes` for Win32 clipboard (smaller frozen binary) and `win10toast` for notifications. Don't add heavy COM dependencies.
- **Adding an HTTP API to the daemon.** The daemon is a single-threaded polling loop, not a web server. AHK and the daemon communicate via lock files. No REST, no WebSocket, no FastAPI.
- **Mixing AHK v1 and v2 syntax.** The project uses AHK v1.1. V2 is a different language with breaking syntax changes.
- **Logging API keys.** Keys come from `config.json` and must never appear in `voiceflow.log` or console output.

---

## 9. Tooling Preferences (Windows-first)

- **Shell:** PowerShell is the default on the user's machine; Bash is also available via WSL. Prefer the harness's Bash tool for POSIX scripts and PowerShell for Windows-native commands.
- **Read-only commands run without asking** — `git status`, `git log`, `git diff`, `pytest --collect-only`, file reads, grep.
- **Python execution:** `python src\voiceflow_daemon.py` for local testing (needs `config.json` with real keys). For automated tests, use the test suite in `tests/`.
- **Build:** `build.bat` compiles both the Python daemon (PyInstaller) and AHK script (Ahk2Exe). Output lands in `dist\VoiceFlow-Release\`.
- **No `__pycache__` in commits.** `.gitignore` covers it.
- **AHK compilation requires AutoHotkey v1.1 installed.** If `Ahk2Exe.exe` isn't found, `build.bat` copies the raw `.ahk` source as a fallback.

---

## 10. Key Source Files (verify existence before citing)

| What | Path |
|------|------|
| Python daemon (audio, cloud, clipboard) | [`src/voiceflow_daemon.py`](src/voiceflow_daemon.py) |
| AHK hotkey shim + tray launcher | [`src/VoiceFlow.ahk`](src/VoiceFlow.ahk) |
| Config template | [`config.json.example`](config.json.example) |
| Build script | [`build.bat`](build.bat) |
| Python dependencies | [`requirements.txt`](requirements.txt) |
| PRD v4 (canonical architecture spec) | [`docs/VoiceFlow-PRD-v4.md`](docs/VoiceFlow-PRD-v4.md) |
| PRD v3 (previous revision, reference) | [`docs/VoiceFlow-PRD-v3.md`](docs/VoiceFlow-PRD-v3.md) |
| Test plan | [`tests/README.md`](tests/README.md) |
| Project overview | [`README.md`](README.md) |

When citing a file in code review, comments, or PR descriptions, **verify the path with a quick search first.** Never reference files or sections from memory.

---

## 11. Signaling Contract (AHK ↔ Daemon)

This is the most critical integration point. Both source files must agree on these paths and behaviors exactly.

| Signal | File | Writer | Reader | Lifecycle |
|--------|------|--------|--------|-----------|
| **Recording start** | `%TEMP%\voiceflow_recording.lock` | AHK (creates on key-down) | Daemon (polls for existence) | AHK creates → daemon starts recording |
| **Recording stop** | `%TEMP%\voiceflow_recording.lock` | AHK (deletes on key-up) | Daemon (polls for deletion) | AHK deletes → daemon stops recording |
| **Daemon ready** | `%TEMP%\voiceflow_ready.lock` | Daemon (creates on init) | AHK (polls at startup, 5s timeout) | Daemon creates → AHK enables hotkey |
| **Pipeline result** | Win32 clipboard | Daemon (writes polished text) | AHK (`ClipWait`, 25s timeout) | Daemon writes clipboard → AHK pastes |

Any change to either source file that touches lock file paths, clipboard operations, or the ready signal **must be verified against the other file** to ensure the contract holds.

---

## 12. Hardening Roadmap Awareness

The following are planned for post-PoC but **not in scope now**. If a task starts pulling you toward any of these, stop and confirm with the user.

| Feature | PRD Section | Status |
|---------|-------------|--------|
| Agent mode (Hermes routing via Ctrl+Shift+Space) | §6.4 | Deferred to post-PoC |
| Socket/pipe signaling (replace lock files) | §7.4 | Deferred to hardening |
| Windows Credential Manager (replace plaintext config) | §7.1, §7.4 | Deferred to hardening |
| `hermes_lan` mode (WSL Ollama backend) | §7.4 | Deferred to hardening |
| `pure_local` mode (local whisper.cpp + llama.cpp) | §7.4 | Deferred to hardening |
| Audio callback mode (replace polling) | §9 Q1 | Post-PoC open question |
| Unicode input / UIA injection alternatives | §9 Q2 | Post-PoC open question |
| Retention policy for audio/transcripts/logs | §9 Q3 | Post-PoC open question |

---

## 13. Final Rule

Act like a senior engineer shipping a PoC that must work reliably on old Windows hardware across a mixed fleet. The product's promise is simple: hold a key, talk, get clean text — every time, in every app, with no surprises.

Every change either upholds that promise or breaks it. When in doubt, surface the trade-off to the user instead of deciding silently.
