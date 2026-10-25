@echo off
rem Double-click: stop Sift and keep it stopped (its autostart is paused until you start it again).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sift.ps1" stop
pause
