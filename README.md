# Jarvis Voice Core

Jarvis is a Windows-first, voice-first desktop assistant designed to feel alive.

This build focuses on a low-friction local setup:

- Double-clap can launch Jarvis from the background after Windows sign-in.
- `Hey Jarvis` wakes the active session.
- Local Ollama can handle conversation without cloud credits.
- Edge TTS can speak back for free without ElevenLabs.
- The HUD shows status, logs, and typed commands.

## Why This Repo Exists

The goal is simple: make Jarvis feel present on a real Windows PC without requiring paid credits just to use him day to day.

This version is designed around:

- A strong local-first setup
- Fast wake and response flow
- Double-clap launch after Windows sign-in
- A simple install path for non-developers

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [Command Examples](docs/COMMANDS.md)

## What This Version Can Do

- Listen for a wake phrase and keep the session open
- Launch from a double clap through a hidden Windows startup listener
- Talk back with offline speech
- Use local Ollama when cloud credits are unavailable
- Open apps, open sites, search Google, and search YouTube
- Keep short session memory

## Requirements

- Windows 10 or Windows 11
- Python 3.12+
- A working microphone
- Speakers or headphones
- Internet only if you want cloud LLMs or online search

## Recommended Free Local Setup

This is the easiest setup for most people.

1. Install Python 3.12 or newer.
2. Install Ollama from [https://ollama.com](https://ollama.com).
3. Pull a local model:

```powershell
ollama pull llama3.2:3b-instruct
```

4. Open PowerShell in this folder and run:

```powershell
Set-Location "C:\path\to\jarvis"
.\setup_jarvis.ps1
```

5. Copy `.env.example` to `.env` if it does not already exist:

```powershell
Copy-Item .env.example .env
```

6. Make sure these values stay enabled inside `.env`:

```env
LOCAL_ONLY_MODE=true
LOCAL_LLM_FALLBACK=true
FORCE_OFFLINE_TTS=true
CLAP_DETECTION_ENABLED=true
REQUIRE_WAKE_PREFIX=true
OLLAMA_MODEL=llama3.2:3b-instruct
```

7. Install clap autostart:

```powershell
.\enable_clap_autostart.ps1
```

8. Start Jarvis once manually:

```powershell
.\start_jarvis.ps1
```

After that, sign into Windows and double-clap to launch him from the background.

## Local vs Cloud Modes

### Local-first mode

Best if you want zero recurring API cost.

- Uses Ollama for the model
- Uses offline TTS by default
- Keeps clap launch and HUD working locally

### Cloud-enhanced mode

Best if you want stronger model quality or premium voice output.

- Anthropic or OpenRouter for the LLM
- ElevenLabs for premium voice output
- Picovoice for dedicated Porcupine wake-word support

## Optional Cloud Setup

If you want Anthropic, OpenRouter, ElevenLabs, or Picovoice support, fill in the matching values in `.env`.

- `ANTHROPIC_API_KEY` for Anthropic
- `OPENROUTER_API_KEY` for OpenRouter
- `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` for premium voice output
- `PICOVOICE_ACCESS_KEY` for Porcupine wake-word detection

If you use ElevenLabs, change:

```env
FORCE_OFFLINE_TTS=false
```

If you want direct Porcupine wake-word support instead of the speech-prefix path, set:

```env
PICOVOICE_ACCESS_KEY=your_key_here
```

## Daily Use

### Start Jarvis manually

```powershell
.\start_jarvis.ps1
```

### Enable clap launch at Windows startup

```powershell
.\enable_clap_autostart.ps1
```

### Disable clap launch

```powershell
.\disable_clap_autostart.ps1
```

### Typical voice flow

1. Sign into Windows.
2. Double-clap to launch Jarvis.
3. Say `Hey Jarvis`.
4. Speak normally after he wakes.
5. Say `go to sleep` if you want him back in standby.

## Useful Example Commands

- `Hey Jarvis, open YouTube in Chrome`
- `search YouTube for Interstellar soundtrack`
- `open Netflix`
- `what year is it`
- `open Gmail`
- `open Spotify`
- `what is the weather today`
- `go to sleep`

## Troubleshooting

### Jarvis does not speak

- Keep `FORCE_OFFLINE_TTS=true` for the free setup.
- Make sure Edge is installed on Windows for `edge-tts`.
- If needed, switch to:

```env
OFFLINE_TTS_ENGINE=powershell
```

### Double-clap does not open Jarvis

- Re-run:

```powershell
.\enable_clap_autostart.ps1
```

- Sign out and back into Windows once so Startup entries refresh.
- Make sure `CLAP_DETECTION_ENABLED=true` in `.env`.
- Avoid very noisy rooms when testing.

### Jarvis says the local model is unavailable

- Start Ollama:

```powershell
ollama serve
```

- Then confirm the model exists:

```powershell
ollama list
```

### Microphone errors

- Check Windows microphone permissions
- Make sure no other app has locked the device
- Restart Jarvis after reconnecting the mic

## Project Files

- `main.py` orchestrates the voice loop
- `listen.py` handles mic capture, clap detection, and STT
- `brain.py` handles LLM replies and streaming text
- `speak.py` handles voice output and sound playback
- `launcher.py` is the hidden clap-to-open background process
- `install_autostart.py` installs or removes the Windows Startup entry

## Security Notes

- Do not commit your real `.env`
- Review any cloud API keys before sharing your setup
- Treat app-launching and system-control commands with care

## Quick Start Summary

```powershell
Set-Location "C:\path\to\jarvis"
.\setup_jarvis.ps1
Copy-Item .env.example .env
.\enable_clap_autostart.ps1
.\start_jarvis.ps1
```
