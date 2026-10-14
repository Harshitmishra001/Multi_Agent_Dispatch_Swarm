@echo off
title Disaster Coordinator Launcher
cd /d "%~dp0"

echo ===================================================
echo Starting Disaster Coordinator Full-Stack Server...
echo ===================================================

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe run.py
) else (
    python run.py
)

pause
