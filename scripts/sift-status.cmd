@echo off
rem Double-click: is Sift running? Processes, health, tunnel, backups, recent errors.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sift.ps1" status
pause
