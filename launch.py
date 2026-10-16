"""
launch.py
---------
Double-click this file to launch the EMA Survey Counter.

Why a .py launcher instead of a .bat/.command file: double-clicking a .py
file runs it with whatever Python is already associated with .py on that
computer (Windows sets this up automatically when Python is installed,
independent of whether Python was added to the system PATH). A .bat file,
by contrast, depends on 'python' being found on PATH, which trips up a lot
of lab computers where Python was installed without that box checked.
This script uses sys.executable (the interpreter that's already running
it) instead of hunting for "python" on PATH, so it works either way.

First run takes a minute or two (installs packages into a private
environment). After that it's quick.
"""

import subprocess
import sys
import venv
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
APP_FILE = APP_DIR / "app.py"
REQUIREMENTS_FILE = APP_DIR / "requirements.txt"

# The environment lives OUTSIDE this folder, in your home directory. If this
# folder is synced via Box Drive (or similar), keeping the environment out of
# it avoids slow syncing and file-lock errors. It's separate from the EMA ->
# REDCap Uploader's environment, so the two tools can't interfere.
VENV_DIR = Path.home() / ".temptations_survey_counter" / "venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv():
    if venv_python().exists():
        return
    print("Setting up environment (first run only, this can take a minute)...")
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True).create(VENV_DIR)


def install_requirements():
    print("Checking dependencies...")
    subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS_FILE)],
        check=True,
    )


def run_dashboard():
    print("Launching EMA Survey Counter in your browser...")
    print("(Leave this window open while you use the dashboard. Close it, or press")
    print(" Ctrl+C in it, when you're done.)\n")
    subprocess.run(
        [str(venv_python()), "-m", "streamlit", "run", str(APP_FILE)],
        cwd=str(APP_DIR),
    )


def main():
    try:
        ensure_venv()
        install_requirements()
        run_dashboard()
    except subprocess.CalledProcessError as e:
        print(f"\nSomething went wrong while setting things up: {e}")
        input("Press Enter to close...")
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001 - this is a top-level launcher, want to catch everything
        print(f"\nUnexpected error: {e}")
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
