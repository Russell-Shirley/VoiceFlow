; VoiceFlow.ahk — Hotkey listener + daemon launcher
;
; This script captures Ctrl+Space for push-to-talk dictation,
; manages the daemon lifecycle, and handles focus-safe clipboard injection.
;
; See docs/VoiceFlow-PRD-v4.md for full architecture documentation.

#NoEnv
SendMode Input
SetWorkingDir %A_ScriptDir%
#SingleInstance Force

; ── Paths ──
ReadyFile := A_Temp . "\voiceflow_ready.lock"
LockFile := A_Temp . "\voiceflow_recording.lock"
DaemonExe := A_ScriptDir . "\voiceflow_daemon.exe"

; ── Startup: Ensure daemon is running ──

; Clean up stale lock files from previous crash
if (FileExist(LockFile))
    FileDelete, %LockFile%
if (FileExist(ReadyFile))
    FileDelete, %ReadyFile%

; Check if daemon is already running
Process, Exist, voiceflow_daemon.exe
if (!ErrorLevel) {
    if (!FileExist(DaemonExe)) {
        MsgBox, 16, VoiceFlow, voiceflow_daemon.exe not found in %A_ScriptDir%.`n`nRun build.bat first or place the daemon binary next to VoiceFlow.exe.
        ExitApp
    }
    Run, %DaemonExe%,, Hide
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

; Configure tray
Menu, Tray, Tip, VoiceFlow — Hold Ctrl+Space to dictate
TrayTip, VoiceFlow, Ready — hold Ctrl+Space to dictate., 3, 1

; ── Push-To-Talk ──
^Space::
    ; 1. Capture active window HWND for focus-safety check
    WinGet, OrigHwnd, ID, A

    ; 2. Pre-Flight Memoization: Backup clipboard
    ClipSaved := ClipboardAll
    Clipboard := ""

    ; 3. Signal recording start (write lock file)
    FileAppend, active, %LockFile%

    ; 4. Block while user holds key
    KeyWait, Space

    ; 5. Signal recording stop (delete lock file)
    FileDelete, %LockFile%

    ; 6. Wait for daemon to write clipboard (25s timeout)
    ClipWait, 25
    if (!ErrorLevel) {
        ; 7. Focus-safety: verify window hasn't changed
        WinGet, CurrentHwnd, ID, A
        if (CurrentHwnd = OrigHwnd) {
            ; Inject via universal paste
            Send, ^v
            Sleep, 150
            ; Restore original clipboard
            Clipboard := ClipSaved
        } else {
            ; Focus changed — leave text on clipboard for manual paste
            TrayTip, VoiceFlow, Focus changed — text left on clipboard., 5, 2
        }
    } else {
        ; Pipeline timed out
        TrayTip, VoiceFlow, Transcription timed out., 5, 3
        ; Restore original clipboard
        Clipboard := ClipSaved
    }

    ClipSaved := ""
return

; ── Clean exit ──
OnExit:
    ; Clean up lock files
    if (FileExist(LockFile))
        FileDelete, %LockFile%
    ; Note: don't delete ReadyFile — daemon manages its own lifecycle
ExitApp
