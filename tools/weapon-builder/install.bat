@echo off
REM Windows: double-click to install. Run "install.bat --uninstall" to restore the original game.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3 is required: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (
  echo First run: setting up Python environment...
  python -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\pip install -q -r requirements.txt || (pause & exit /b 1)
)
.venv\Scripts\python -I tools\install.py %*
pause
