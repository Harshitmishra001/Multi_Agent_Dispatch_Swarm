"""
Disaster Coordinator — Unified Full-Stack Local Launcher.

Runs the FastAPI backend and Vite frontend concurrently in a single process,
multiplexing output and shutting down both servers cleanly on Ctrl+C.

Usage:
    python run.py
"""

import os
import sys
import time
import signal
import subprocess
import shutil

# Root directory of the repository
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

# Prefer virtual environment python if it exists
VENV_PYTHON = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(VENV_PYTHON):
    PYTHON_EXE = VENV_PYTHON
else:
    PYTHON_EXE = sys.executable

def print_banner():
    banner = """
========================================================================
🚨  DISASTER COORDINATOR — FULL STACK LOCAL SERVER
========================================================================
📡  Backend API:        http://127.0.0.1:8000
📖  Interactive Docs:   http://127.0.0.1:8000/docs
📊  Prometheus Metrics: http://127.0.0.1:8000/metrics
🌐  WebSocket Stream:   ws://127.0.0.1:8000/ws
💻  Tactical Dashboard: http://localhost:5173
🔐  Default Reviewer:   alice / reviewer_pass
🔐  Default Admin:      admin / admin_pass
========================================================================
Press Ctrl+C to shut down both backend and frontend cleanly.
========================================================================
"""
    print(banner)

def main():
    print_banner()

    # Find npm binary
    npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm_cmd:
        print("❌ Error: Node.js / npm not found on PATH. Please install Node.js.")
        sys.exit(1)

    # 1. Start Backend process
    backend_cmd = [
        PYTHON_EXE,
        "-m", "uvicorn",
        "backend.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--reload"
    ]
    print(f"🚀 Starting Backend (FastAPI on :8000)...")
    backend_proc = subprocess.Popen(
        backend_cmd,
        cwd=ROOT_DIR,
    )

    # Allow backend 1 second to bind port
    time.sleep(1)

    # 2. Start Frontend process
    frontend_cmd = [npm_cmd, "run", "dev"]
    print(f"🚀 Starting Frontend (Vite React on :5173)...")
    frontend_proc = subprocess.Popen(
        frontend_cmd,
        cwd=FRONTEND_DIR,
    )

    procs = [backend_proc, frontend_proc]

    def terminate_all(*args):
        print("\n🛑 Shutting down Disaster Coordinator servers...")
        for p in procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        time.sleep(0.5)
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        print("✅ All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, terminate_all)
    signal.signal(signal.SIGTERM, terminate_all)

    # Monitor processes
    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    # One of the processes exited unexpectedly
                    print(f"⚠️ Process {p.args} exited with code {p.returncode}")
                    terminate_all()
            time.sleep(0.5)
    except KeyboardInterrupt:
        terminate_all()

if __name__ == "__main__":
    main()
