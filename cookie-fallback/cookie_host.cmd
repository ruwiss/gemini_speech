@echo off
cd /d "%~dp0"
if exist "%~dp0cookie_host.exe" (
  "%~dp0cookie_host.exe"
  exit /b %errorlevel%
)
set PYTHONPATH=%~dp0
python -u "%~dp0cookie_host.py"
