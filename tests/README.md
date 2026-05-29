# Tests

Test scripts for VoiceFlow components.

## Planned tests (PoC)

- **test_cloud_pipeline.py** — Mock Whisper and OpenRouter responses, verify retry/timeout behavior
- **test_clipboard.py** — Verify clipboard backup/restore and retry logic
- **test_config.py** — Verify config loading, missing key detection, and error messages
- **test_recording_cap.py** — Verify 90-second max recording enforcement
