"""Manage the hidden Jarvis clap launcher entry in Windows Startup.

This module writes or removes a small VBScript in the current user's
Startup folder so the background clap listener can be enabled or disabled.
"""

from __future__ import annotations

from pathlib import Path

from config import CLAP_DETECTION_ENABLED


def _get_startup_file() -> Path:
    """Return the Startup shortcut path used for the Jarvis clap launcher."""
    startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    return startup_dir / "Jarvis Clap Launcher.vbs"


def _resolve_pythonw(base_dir: Path) -> Path:
    """Choose the hidden-capable interpreter from the project virtual environment."""
    scripts_dir = base_dir / ".venv" / "Scripts"
    pythonw_path = scripts_dir / "pythonw.exe"
    if pythonw_path.exists():
        return pythonw_path

    python_path = scripts_dir / "python.exe"
    if python_path.exists():
        return python_path

    raise FileNotFoundError("Could not find pythonw.exe or python.exe in jarvis\\.venv\\Scripts.")


def _build_vbs_command(python_path: Path, launcher_path: Path) -> str:
    """Build the VBScript contents that launch the hidden clap listener."""
    python_text = str(python_path).replace('"', '""')
    launcher_text = str(launcher_path).replace('"', '""')
    command = f'"{python_text}" "{launcher_text}"'
    return (
        'Set shell = CreateObject("WScript.Shell")\r\n'
        f'shell.Run "{command.replace(chr(34), chr(34) * 2)}", 0, False\r\n'
    )


def install_autostart() -> Path:
    """Create or update the user's Startup entry for the Jarvis clap launcher."""
    base_dir = Path(__file__).resolve().parent
    startup_file = _get_startup_file()
    python_path = _resolve_pythonw(base_dir)
    launcher_path = base_dir / "launcher.py"

    startup_file.write_text(_build_vbs_command(python_path, launcher_path), encoding="utf-8")
    return startup_file


def uninstall_autostart() -> Path:
    """Remove the user's Startup entry for the Jarvis clap launcher if present."""
    startup_file = _get_startup_file()
    if startup_file.exists():
        startup_file.unlink()
    return startup_file


def main() -> None:
    """Install or remove the startup file based on the current clap setting."""
    if CLAP_DETECTION_ENABLED:
        startup_file = install_autostart()
        print(f"[INFO] Installed Jarvis clap launcher autostart: {startup_file}")
    else:
        startup_file = uninstall_autostart()
        print(f"[INFO] Removed Jarvis clap launcher autostart: {startup_file}")


if __name__ == "__main__":
    """Run the installer when executed directly."""
    main()
