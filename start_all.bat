@echo off
set "ROOT=%~dp0"

rem backend
if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
    echo [ERROR] venv not found. Run these in backend first:
    echo     python -m venv .venv
    echo     .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" /d "%ROOT%backend" cmd /k ".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app"

rem frontend
start "" /d "%ROOT%frontend" cmd /k "npm run dev"
