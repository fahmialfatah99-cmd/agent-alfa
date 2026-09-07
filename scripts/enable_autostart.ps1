# ==============================================================================
# ALFA SOVEREIGN AI AGENT - AKTIVASI AUTO-START WINDOWS (24/7 AUTO-RUN & AUTO-HEAL)
# ==============================================================================
[CmdletBinding()]
param()

$dir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $dir

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  MENGAKTIFKAN AUTO-START ALFA SOVEREIGN AI (WINDOWS)" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Buat Silent VBScript Launcher
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$dir\alfa_guardian.ps1""", 0, False
"@

$vbsPath = "$dir\launch_guardian_hidden.vbs"
Set-Content -Path $vbsPath -Value $vbsContent -Encoding UTF8
Write-Host "   [OK] File peluncur silent VBScript dibuat: $vbsPath" -ForegroundColor Green

# 2. Daftarkan ke Startup Folder Windows (Double-Redundancy)
$startupDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$startupVbs = Join-Path $startupDir "ALFA_AutoStart.vbs"
Copy-Item $vbsPath $startupVbs -Force
Write-Host "   [OK] Shortcut startup didaftarkan di: $startupVbs" -ForegroundColor Green

# 3. Daftarkan Task Scheduler (AtLogon)
$taskName = "ALFA_Sovereign_Guardian"
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`"" -WorkingDirectory $dir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "ALFA Sovereign AI Auto-Heal Guardian (Bot + Web Dashboard + 9Router)" -ErrorAction Stop | Out-Null
    Write-Host "   [OK] Windows Scheduled Task '$taskName' berhasil didaftarkan!" -ForegroundColor Green
} catch {
    Write-Host "   [INFO] Task Scheduler memerlukan hak administrator, auto-start tetap aktif via Startup Folder." -ForegroundColor Yellow
}

# 4. Jalankan Guardian & Semua Layanan Sekarang
Write-Host ""
Write-Host "[*] Meluncurkan seluruh service ALFA secara instan di latar belakang..." -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\start_alfa.ps1"
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbsPath`"" -WorkingDirectory $dir -WindowStyle Hidden

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  🎉 AUTO-START BERHASIL DIAKTIFKAN!" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  ✅ Layanan yang otomatis aktif saat komputer dinyalakan:"
Write-Host "     1. 🤖 Telegram AI Bot" -ForegroundColor White
Write-Host "     2. 🌐 Web Management Dashboard (http://localhost:8080)" -ForegroundColor White
Write-Host "     3. 🔀 9Router AI Gateway (http://localhost:20128)" -ForegroundColor White
Write-Host "     4. 🛡️ ALFA Guardian (Auto-Heal pemantau otomatis 24/7)" -ForegroundColor White
Write-Host ""
