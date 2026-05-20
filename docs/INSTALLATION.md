# Installation Guide

This guide is for someone setting up Jarvis on a fresh Windows machine.

## 1. Install Base Tools

Install these first:

- Python 3.12 or newer
- Ollama
- Microsoft Edge

Recommended links:

- Python: [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/)
- Ollama: [https://ollama.com](https://ollama.com)

## 2. Download the Project

If you cloned the repo already, open PowerShell in the project folder:

```powershell
Set-Location "C:\path\to\jarvis"
```

## 3. Run the Setup Script

```powershell
.\setup_jarvis.ps1
```

What it does:

- creates `.venv` if missing
- upgrades `pip`
- installs Python dependencies
- creates `.env` from `.env.example` if needed

## 4. Prepare the Local Model

Install a default local model:

```powershell
ollama pull llama3.2:3b-instruct
```

If Ollama is not already running:

```powershell
ollama serve
```

## 5. Confirm the Recommended Free Settings

Open `.env` and make sure these are set:

```env
LOCAL_ONLY_MODE=true
LOCAL_LLM_FALLBACK=true
FORCE_OFFLINE_TTS=true
CLAP_DETECTION_ENABLED=true
REQUIRE_WAKE_PREFIX=true
OLLAMA_MODEL=llama3.2:3b-instruct
```

## 6. Enable Clap Launch

```powershell
.\enable_clap_autostart.ps1
```

This installs the hidden Windows Startup listener and starts it immediately.

## 7. Start Jarvis Manually Once

```powershell
.\start_jarvis.ps1
```

After that, future sessions can use the clap launcher after Windows sign-in.

## 8. Test the Expected Flow

1. Sign into Windows.
2. Double-clap.
3. Wait for Jarvis to appear.
4. Say `Hey Jarvis`.
5. Ask something simple like `what year is it`.

## Optional Premium Setup

If you want stronger cloud features, fill in these values in `.env`:

- `ANTHROPIC_API_KEY`
- `OPENROUTER_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `PICOVOICE_ACCESS_KEY`

If you want ElevenLabs voice output:

```env
FORCE_OFFLINE_TTS=false
```

## If Something Breaks

Run these checks:

```powershell
ollama list
.\.venv\Scripts\python.exe .\main.py
```

If clap launch is not responding:

```powershell
.\disable_clap_autostart.ps1
.\enable_clap_autostart.ps1
```
