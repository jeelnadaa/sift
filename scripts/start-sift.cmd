@echo off
rem Double-click: start Sift (and turn its autostart back on).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sift.ps1" start
pause
