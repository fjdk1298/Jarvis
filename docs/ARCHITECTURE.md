# Architecture Overview

Jarvis is built as a continuous voice loop with optional background launch support.

## Main Runtime Flow

1. Sleep
2. Wake
3. Listen
4. Think
5. Speak
6. Return to sleep or active standby

## Core Modules

### `main.py`

Coordinates the entire runtime:

- startup sequence
- HUD updates
- wake and listen flow
- local action handling
- model replies
- TTS playback
- interruption handling

### `listen.py`

Handles microphone-facing logic:

- speech recognition input
- clap detection
- wake signal recognition
- barge-in interruption detection

### `brain.py`

Handles response generation:

- local or cloud model routing
- short memory usage
- live web context injection when needed
- sentence streaming to speech output

### `speak.py`

Handles output audio:

- ElevenLabs streaming when enabled
- Edge/offline fallback speech
- wake and error sounds
- interruption-aware stopping

### `launcher.py`

Runs as a hidden background process after Windows sign-in:

- listens for double-clap
- launches the main Jarvis app
- avoids duplicate launches

### `install_autostart.py`

Creates or removes the Windows Startup entry for clap launch.

## Local-First Design

The repo is intentionally tuned for free and repeatable use:

- Ollama is the recommended default model backend
- Edge TTS is the recommended default speech backend
- Clap launch does not rely on cloud APIs

## Wake Modes

### Clap launch mode

- Background listener starts with Windows
- Double-clap launches Jarvis

### Direct speech wake mode

- Once Jarvis is open, `Hey Jarvis` activates the session
- Session can stay active until sleep mode is requested

### Picovoice mode

If `PICOVOICE_ACCESS_KEY` is set, Jarvis can use Porcupine-based wake detection.

## UX Goals

- low friction startup
- minimal silence between listen and reply
- graceful fallback when premium services are unavailable
- visible runtime state through the HUD
