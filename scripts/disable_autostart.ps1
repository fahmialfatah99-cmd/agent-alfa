# ==============================================================================
# ALFA SOVEREIGN AI AGENT - NONAKTIFKAN AUTO-START WINDOWS
# ==============================================================================
[CmdletBinding()]
param()

$dir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $dir

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  MENONAKTIFKAN AUTO-START ALFA SOVEREIGN AI (WINDOWS)" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Hapus dari Startup Folder
$startupDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$startupVbs = Join-Path $startupDir "ALFA_AutoStart.vbs"
if (Test-Path $startupVbs) {
    Remove-Item $startupVbs -Force
    Write-Host "   [OK] File startup shortcut dihapus: $startupVbs" -ForegroundColor Green
}

# 2. Hapus dari Task Scheduler
$taskName = "ALFA_Sovereign_Guardian"
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "   [OK] Windows Scheduled Task '$taskName' dinonaktifkan." -ForegroundColor Green
} catch {}

Write-Host ""
Write-Host "Auto-start ALFA telah berhasil dinonaktifkan." -ForegroundColor Yellow
Write-Host ""
