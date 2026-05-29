@echo off
REM VoiceFlow Build Script
REM Compiles Python daemon and AHK script into standalone binaries.
REM
REM Requirements:
REM   - Python 3.8+ with pip
REM   - AutoHotkey v1.1+ installed (for Ahk2Exe compiler)
REM
REM Output: dist\VoiceFlow-Release\

echo ========================================
echo  VoiceFlow Build
echo ========================================
echo.

REM ── Step 1: Install Python dependencies ──
echo [1/4] Installing Python dependencies...
pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip install failed.
    exit /b 1
)

REM ── Step 2: Compile Python daemon ──
echo [2/4] Compiling voiceflow_daemon.py with PyInstaller...
pyinstaller --noconsole --onefile --distpath dist\build src\voiceflow_daemon.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller compilation failed.
    exit /b 1
)

REM ── Step 3: Compile AHK script ──
echo [3/4] Compiling VoiceFlow.ahk...
REM Try standard install paths for Ahk2Exe
set AHK2EXE=
if exist "%ProgramFiles%\AutoHotkey\Compiler\Ahk2Exe.exe" (
    set "AHK2EXE=%ProgramFiles%\AutoHotkey\Compiler\Ahk2Exe.exe"
) else if exist "%ProgramFiles(x86)%\AutoHotkey\Compiler\Ahk2Exe.exe" (
    set "AHK2EXE=%ProgramFiles(x86)%\AutoHotkey\Compiler\Ahk2Exe.exe"
) else (
    echo WARNING: Ahk2Exe.exe not found. Copying .ahk source instead.
    echo          Install AutoHotkey to compile to .exe.
    copy src\VoiceFlow.ahk dist\build\VoiceFlow.ahk >nul
    goto :package
)

"%AHK2EXE%" /in src\VoiceFlow.ahk /out dist\build\VoiceFlow.exe
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: AHK compilation failed.
    exit /b 1
)

:package
REM ── Step 4: Assemble release package ──
echo [4/4] Assembling release package...
if exist dist\VoiceFlow-Release rmdir /s /q dist\VoiceFlow-Release
mkdir dist\VoiceFlow-Release

copy dist\build\voiceflow_daemon.exe dist\VoiceFlow-Release\ >nul 2>nul
if exist dist\build\VoiceFlow.exe (
    copy dist\build\VoiceFlow.exe dist\VoiceFlow-Release\ >nul
) else (
    copy dist\build\VoiceFlow.ahk dist\VoiceFlow-Release\ >nul
)
copy config.json.example dist\VoiceFlow-Release\config.json >nul

echo.
echo ========================================
echo  Build complete!
echo ========================================
echo.
echo Release package: dist\VoiceFlow-Release\
echo.
echo Next steps:
echo   1. Edit dist\VoiceFlow-Release\config.json with your API keys
echo   2. Set openrouter_model to the cheapest viable model
echo   3. Run VoiceFlow.exe
echo.
dir dist\VoiceFlow-Release\
