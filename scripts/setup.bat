@echo off
chcp 65001 >nul
title ALFA Sovereign AI - 1-Click Interactive Setup Wizard
color 0b

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

echo.
echo Tekan tombol apa saja untuk menutup jendela ini...
pause >nul
