@echo off
chcp 65001 >nul
title ALFA Sovereign AI - Enable Windows Auto-Start
color 0b

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_autostart.ps1"

echo.
pause
