@echo off
cd /d "%~dp0"
echo Starting Courtside Edge 0.16.0...
set "PYTHONUTF8=1"
set "EDGE_PY=python"
where python >nul 2>&1
if errorlevel 1 (
 if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
  set "EDGE_PY=%LocalAppData%\Programs\Python\Python311\python.exe"
 ) else (
  goto failed
 )
)
if exist .runtime\fastapi\__init__.py (
 goto ready
)
if not exist .venv\Scripts\python.exe "%EDGE_PY%" -m venv .venv
if not exist .venv\Scripts\python.exe goto failed
set "EDGE_PY=.venv\Scripts\python.exe"
"%EDGE_PY%" -c "import fastapi, uvicorn, httpx, multipart, PIL, tzdata, bs4" >nul 2>&1
if not errorlevel 1 goto ready
"%EDGE_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:ready
echo Open http://127.0.0.1:8765 if your browser does not open.
set "EDGE_OPEN_BROWSER=1"
"%EDGE_PY%" run.py
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11 or newer, check your internet, and try again.
pause
exit /b 1


