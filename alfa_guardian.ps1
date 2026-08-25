# ALFA Guardian — auto-heal bot & dashboard + alarm Telegram + rotasi log + cleanup disk
$dir = "C:\Users\mj9\telegram-ai-bot"
$env:PYTHONUTF8 = "1"

# ── Baca .env minimal ──
$envMap = @{}
Get-Content "$dir\.env" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)\s*$') { $envMap[$Matches[1]] = $Matches[2].Trim() }
}
$token = $envMap["TELEGRAM_BOT_TOKEN"]
$chat  = ($envMap["ALLOWED_USER_IDS"] -split ",")[0].Trim()

function Send-Alert($msg) {
    if (-not $token -or -not $chat) { return }
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" -Method Post `
            -Body (@{ chat_id = $chat; text = $msg } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 10 | Out-Null
    } catch {}
}

function Test-Proc($hint) {
    return [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $hint } | Select-Object -First 1)
}

$prevBot = $true
$prevDash = $true
$lastCleanupDay = (Get-Date).Date

while ($true) {
    try {
        $botUp  = Test-Proc 'bot\.py'
        $dashUp = Test-Proc 'web_dashboard\.py'

        if (-not $botUp -or -not $dashUp) {
            # Konfirmasi 5 detik (hindari false positive saat restart manual)
            Start-Sleep -Seconds 5
            $botUp  = Test-Proc 'bot\.py'
            $dashUp = Test-Proc 'web_dashboard\.py'
        }

        if (-not $botUp -or -not $dashUp) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\start_alfa.ps1"
            Start-Sleep -Seconds 20
            $botNew  = Test-Proc 'bot\.py'
            $dashNew = Test-Proc 'web_dashboard\.py'

            if (($prevBot -and -not $botNew) -or ($prevDash -and -not $dashNew)) {
                Send-Alert ("🛡️ ALFA GUARDIAN`n`nDeteksi layanan mati -> auto-restart dijalankan.`n🤖 Bot: " +
                    $(if ($botNew) { "✅ hidup kembali" } else { "❌ gagal bangkit" }) +
                    "`n🌐 Dashboard: " +
                    $(if ($dashNew) { "✅ hidup kembali" } else { "❌ gagal bangkit" }))
            }
            $prevBot  = $botNew
            $prevDash = $dashNew
        }
        else {
            $prevBot  = $true
            $prevDash = $true
        }

        # ── Rotasi log >20MB (simpan 500 baris terakhir) ──
        foreach ($log in @("bot_err.log", "bot_out.log", "dash_out.log", "dash_err.log")) {
            $p = Join-Path $dir $log
            if ((Test-Path $p) -and ((Get-Item $p).Length -gt 20MB)) {
                $tail = Get-Content $p -Tail 500 -ErrorAction SilentlyContinue
                Set-Content -Path $p -Value $tail -Encoding UTF8
            }
        }

        # ── Cleanup harian: node_modules proyek mati (>7 hari) di sandbox ──
        if ((Get-Date).Hour -ge 13 -and $lastCleanupDay -ne (Get-Date).Date) {
            $lastCleanupDay = (Get-Date).Date
            Get-ChildItem "C:\dev\shm\alfa_sandbox" -Directory -Recurse -Filter "node_modules" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        }
    } catch {}

    Start-Sleep -Seconds 60
}
