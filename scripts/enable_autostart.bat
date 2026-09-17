@echo off
chcp 65001 >nul
title ALFA Sovereign AI - Enable Windows Auto-Start
color 0b

cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_autostart.ps1"

echo.
pause
