@echo off
setlocal
cd /d "%~dp0.."
set "MODEL_PROVIDER=openai_compat"
python -m uvicorn app:app --host 127.0.0.1 --port 8765 --workers 1
endlocal
