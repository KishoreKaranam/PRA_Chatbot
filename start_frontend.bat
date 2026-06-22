@echo off
echo =========================================================
echo  PRA Chatbot - Starting Frontend (Streamlit)
echo =========================================================

cd /d "%~dp0frontend"

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

echo [INFO] Starting Streamlit frontend on http://localhost:8501
start "PRA Chatbot Frontend" cmd /k "cd /d %~dp0frontend && call venv\Scripts\activate.bat && streamlit run app.py --server.port 8501 --server.headless false"
