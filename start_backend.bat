@echo off
echo =========================================================
echo  PRA Chatbot - Starting Backend (FastAPI)
echo =========================================================

cd /d "%~dp0backend"

if not exist ".env" (
    echo [WARNING] .env not found. Copying .env.example ...
    copy "..\\.env.example" ".env"
)

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

echo [INFO] Starting FastAPI backend on http://localhost:8000
start "PRA Chatbot Backend" cmd /k "cd /d %~dp0backend && call venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
