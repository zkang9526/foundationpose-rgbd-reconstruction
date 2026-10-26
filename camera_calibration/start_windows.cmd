@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_windows.ps1" %*
if errorlevel 1 pause
