@echo off
REM Canonical Ollama launcher is the PowerShell script beside this wrapper.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_small_brain_ollama.ps1" %*
exit /b %errorlevel%
