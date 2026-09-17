"""Background proactive and watchdog loops for ALFA Telegram Bot."""

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil
from telegram.ext import Application

import token_usage
from alfa import tools
from alfa.bot.config import (
    ALLOWED_USER_IDS,
    OWNER_NAME,
    _main_brain_gemini_model,
    gemini_client,
    resolve_main_gemini,
)
from alfa.bot.helpers import safe_send_message
from alfa.bot.turn_executor import run_agent_turn
from alfa.core import database
from alfa.tools import SANDBOX_DIR

logger = logging.getLogger("TelegramAIAgent")


async def proactive_reminder_loop(application: Application):
    """Background task to poll and send scheduled reminders."""
    logger.info("Proactive reminder dispatcher started.")
    while True:
        try:
            due_reminders = await database.get_due_reminders()
            for r in due_reminders:
                rem_id = r["id"]
                chat_id = r["chat_id"]
                msg = r["message"]
                rem_time = r["reminder_time"]

                alert_text = (
                    f"⏰ **PENGINGAT OTOMATIS (REMINDER #{rem_id})**\n\n"
                    f"📌 **Pesan:** {msg}\n"
                    f"🕒 **Waktu:** `{rem_time}`"
                )
                try:
                    await safe_send_message(application, chat_id, alert_text)
                    await database.mark_reminder_executed(rem_id)
                    logger.info(f"Dispatched reminder #{rem_id} to chat {chat_id}")
                except Exception as send_err:
                    logger.error(
                        f"Failed to dispatch reminder #{rem_id}: {send_err}. Will retry."
                    )
                    try:
                        due_dt = datetime.fromisoformat(rem_time.replace("T", " "))
                        if (datetime.now() - due_dt).total_seconds() > 86400:
                            await database.mark_reminder_executed(rem_id)
                            logger.warning(
                                f"Reminder #{rem_id} dropped: overdue >24h and undeliverable."
                            )
                    except Exception:
                        await database.mark_reminder_executed(rem_id)
        except Exception as e:
            logger.error(f"Error in reminder loop: {e}")

        await asyncio.sleep(20)


async def proactive_cron_watchdog_loop(application: Application):
    """Background task to execute scheduled recurring cron tasks & proactive watchdogs."""
    logger.info("Proactive cron watchdog loop started.")
    while True:
        try:
            due_jobs = await database.get_due_cron_jobs()
            for job in due_jobs:
                job_id = job["id"]
                user_id = job["user_id"]
                chat_id = job["chat_id"]
                title = job["title"]
                prompt = job["prompt_instruction"]
                interval = job["interval_minutes"]

                logger.info(
                    f"Executing recurring cron task #{job_id}: '{title}' for user {user_id}"
                )
                await database.update_cron_job_after_run(job_id, interval)

                cron_prompt = (
                    f"[TUGAS TERJADWAL OTONOM: {title.upper()}]\n"
                    f"Instruksi: {prompt}\n\n"
                    f"Jalankan tugas ini secara otonom menggunakan tools yang relevan dan laporkan hasilnya dengan rapi."
                )
                try:
                    result = await run_agent_turn(
                        user_id=user_id, user_prompt=cron_prompt, chat_id=chat_id
                    )
                    header = f"⏰ **[WATCHDOG / CRON TASK #{job_id}: {title.upper()}]**\n\n{result}"
                    await safe_send_message(application, chat_id, header)

                    if os.path.isdir(SANDBOX_DIR):
                        for fname in os.listdir(SANDBOX_DIR):
                            fpath = os.path.join(SANDBOX_DIR, fname)
                            if tools.is_internal_sandbox_artifact(fname):
                                continue
                            if tools.is_source_code_file(fname):
                                continue
                            if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                                ext = os.path.splitext(fname)[1].lower()
                                try:
                                    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                                        with open(fpath, "rb") as pf:
                                            await application.bot.send_photo(
                                                chat_id=chat_id,
                                                photo=pf,
                                                caption=f"📸 Lampiran Cron: {fname}",
                                            )
                                    else:
                                        with open(fpath, "rb") as df:
                                            await application.bot.send_document(
                                                chat_id=chat_id,
                                                document=df,
                                                caption=f"📄 Lampiran Cron: {fname}",
                                            )
                                    try:
                                        os.remove(fpath)
                                    except OSError:
                                        pass
                                except Exception as attach_err:
                                    logger.error(
                                        f"Failed to send cron attachment {fname}: {attach_err}"
                                    )
                except Exception as run_err:
                    logger.error(f"Error executing cron job #{job_id}: {run_err}")
        except Exception as e:
            logger.error(f"Error in cron watchdog loop: {e}")

        await asyncio.sleep(25)


async def proactive_system_guardian_loop(application: Application):
    """Background daemon that monitors system health 24/7 and takes autonomous protective actions."""
    logger.info("🛡️ God Mode: System Guardian daemon started.")
    config_path = os.path.join(os.path.expanduser("~"), ".alfa", "guardian_config.json")

    while True:
        try:
            if not os.path.exists(config_path):
                await asyncio.sleep(30)
                continue

            with open(config_path, "r") as f:
                config = json.load(f)

            if not config.get("enabled", False):
                await asyncio.sleep(30)
                continue

            alerts = []

            cpu_pct = psutil.cpu_percent(interval=1)
            cpu_thresh = config.get("cpu_threshold", 90)
            if cpu_pct > cpu_thresh:
                alerts.append(
                    f"🔴 **CPU** sangat tinggi: {cpu_pct}% (threshold: {cpu_thresh}%)"
                )

            ram = psutil.virtual_memory()
            ram_thresh = config.get("ram_threshold", 85)
            if ram.percent > ram_thresh:
                alert_msg = f"🔴 **RAM** kritis: {ram.percent}% ({round(ram.used / (1024**3), 1)}/{round(ram.total / (1024**3), 1)} GB)"
                alerts.append(alert_msg)

                if config.get("auto_kill_ram_hogs", False):
                    protected = {
                        "python3",
                        "systemd",
                        "gnome-shell",
                        "Xwayland",
                        "pipewire",
                        "dbus-daemon",
                        "telegram-ai",
                    }
                    killed = []
                    procs = sorted(
                        psutil.process_iter(["pid", "name", "memory_info"]),
                        key=lambda p: (
                            p.info.get("memory_info") or type("", (), {"rss": 0})
                        ).rss,
                        reverse=True,
                    )
                    for p in procs[:5]:
                        try:
                            pname = p.info.get("name", "")
                            if not any(prot in pname.lower() for prot in protected):
                                mem_mb = round(
                                    p.info["memory_info"].rss / (1024 * 1024), 1
                                )
                                if mem_mb > 500:
                                    p.terminate()
                                    killed.append(f"{pname} ({mem_mb}MB)")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    if killed:
                        alerts.append(f"⚡ **Auto-Kill:** {', '.join(killed)}")

            disk = psutil.disk_usage("/")
            disk_thresh = config.get("disk_threshold", 90)
            if disk.percent > disk_thresh:
                alerts.append(
                    f"🔴 **Disk** hampir penuh: {disk.percent}% ({round(disk.free / (1024**3), 1)} GB tersisa)"
                )

            battery = psutil.sensors_battery()
            batt_thresh = config.get("battery_critical", 10)
            if battery and not battery.power_plugged and battery.percent <= batt_thresh:
                alerts.append(
                    f"🔴 **Baterai KRITIS:** {battery.percent}% — Tidak sedang mengisi!"
                )

            if alerts:
                alert_text = "🛡️ **[SYSTEM GUARDIAN ALERT]**\n\n" + "\n".join(alerts)
                for uid in ALLOWED_USER_IDS:
                    try:
                        await safe_send_message(application, uid, alert_text)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Guardian daemon error: {e}")

        await asyncio.sleep(30)


async def proactive_focus_session_loop(application: Application):
    """Background task to poll and notify completed focus/pomodoro sessions."""
    logger.info("🎯 Proactive focus session watchdog started.")
    while True:
        try:
            due_sessions = await database.get_due_focus_sessions()
            for s in due_sessions:
                s_id = s["id"]
                chat_id = s["chat_id"]
                title = s["title"]
                duration = s["duration_minutes"]
                notes = s.get("notes", "")

                alert_text = (
                    f"🎉 **[SESI FOKUS SELESAI!]**\n\n"
                    f"🎯 **Target:** {title}\n"
                    f"⏱️ **Durasi:** {duration} menit\n"
                    f"📝 **Catatan:** {notes if notes else 'Kerja bagus! Istirahatlah sejenak (5-10 menit) sebelum melanjutkan.'}"
                )
                try:
                    await safe_send_message(application, chat_id, alert_text)
                    await database.mark_focus_session_completed(s_id)
                    logger.info(
                        f"Dispatched focus session completion #{s_id} to chat {chat_id}"
                    )
                except Exception as send_err:
                    logger.error(
                        f"Failed to dispatch focus session #{s_id}: {send_err}"
                    )
                    await database.mark_focus_session_completed(s_id)
        except Exception as e:
            logger.error(f"Error in focus session loop: {e}")

        await asyncio.sleep(15)


async def proactive_ambient_agent_loop(application: Application):
    """
    GOD MODE: Ambient Proactive Agent.
    Evaluates real-time ambient context (time of day, battery, system status, active memories)
    and autonomously initiates context-aware check-ins, briefings, or questions to the user.
    """
    logger.info("🤖 Ambient Proactive Agent loop started.")
    config_path = os.path.join(
        os.path.expanduser("~"), ".alfa", "proactive_config.json"
    )

    await asyncio.sleep(60)

    while True:
        cycle_backoff = 600
        try:
            config = {
                "enabled": True,
                "min_hours_between_pings": 3,
                "quiet_hours_start": 23,
                "quiet_hours_end": 7,
            }
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    pass

            if config.get("enabled", True):
                now_dt = datetime.now()
                current_hour = now_dt.hour
                q_start = config.get("quiet_hours_start", 23)
                q_end = config.get("quiet_hours_end", 7)

                today_str = now_dt.strftime("%Y-%m-%d")
                pings_today = (
                    config.get("pings_today", 0)
                    if config.get("last_ping_date") == today_str
                    else 0
                )
                max_pings = int(config.get("max_pings_per_day", 4))

                is_quiet = False
                if q_start > q_end:
                    is_quiet = current_hour >= q_start or current_hour < q_end
                else:
                    is_quiet = q_start <= current_hour < q_end

                if is_quiet or pings_today >= max_pings:
                    pass
                else:
                    last_ping_str = config.get("last_ping_time")
                    should_evaluate = True
                    if last_ping_str:
                        try:
                            last_ping_dt = datetime.fromisoformat(last_ping_str)
                            elapsed_hours = (
                                now_dt - last_ping_dt
                            ).total_seconds() / 3600.0
                            min_hours = config.get("min_hours_between_pings", 3)
                            if elapsed_hours < min_hours:
                                should_evaluate = False
                        except Exception:
                            pass

                    if should_evaluate and gemini_client and ALLOWED_USER_IDS:
                        target_user = ALLOWED_USER_IDS[0]
                        day_names = [
                            "Senin",
                            "Selasa",
                            "Rabu",
                            "Kamis",
                            "Jumat",
                            "Sabtu",
                            "Minggu",
                        ]
                        now_formatted = f"{day_names[now_dt.weekday()]}, {now_dt.strftime('%d %B %Y pukul %H:%M WIB')}"

                        batt = psutil.sensors_battery()
                        batt_status = (
                            f"{batt.percent}% ({'Mengisi daya ⚡' if batt.power_plugged else 'Menggunakan baterai 🔋'})"
                            if batt
                            else "Desktop / AC Power"
                        )
                        ram = psutil.virtual_memory()
                        ram_str = f"RAM terpakai {ram.percent}%"

                        user_memories = await database.get_all_memories(target_user)
                        mem_samples = [
                            f"{m['key_topic']}: {m['content']}"
                            for m in user_memories[:4]
                        ]
                        memories_summary = (
                            "; ".join(mem_samples)
                            if mem_samples
                            else "Belum ada catatan proyek spesifik."
                        )

                        proactive_eval_prompt = (
                            f"Kamu adalah ALFA, asisten AI otonom pribadi {OWNER_NAME} yang cerdas, proaktif, dan memiliki inisiatif sendiri.\n"
                            f"Kondisi real-time saat ini:\n"
                            f"- Waktu: {now_formatted}\n"
                            f"- Baterai: {batt_status}\n"
                            f"- Status Sistem: {ram_str}\n"
                            f"- Catatan Memori Proyek: {memories_summary}\n\n"
                            f"INSTRUKSI:\n"
                            f"Tentukan apakah kamu perlu secara mandiri menyapa, menanyakan progres proyek, atau mengingatkan sesuatu kepada {OWNER_NAME}.\n"
                            f"Pedoman:\n"
                            f"1. Jika waktu saat ini cocok untuk sapaan / check-in produktivitas / saran rehat / follow-up, buatlah pesan pendek yang natural, hangat, dan mengajukan 1 pertanyaan atau tawaran bantuan relevan (maks 2-3 kalimat).\n"
                            f"2. Jika saat ini tidak ada hal yang bernilai tinggi untuk disampaikan, balas hanya satu kata: NO_ACTION.\n"
                            f"3. DILARANG menggunakan format robotik kaku. Bersikaplah seperti partner asisten pribadi profesional."
                        )

                        from google.genai import types

                        p_client, p_key_id, p_key_label = resolve_main_gemini()
                        if not p_client:
                            raise RuntimeError(
                                "Tidak ada API key Gemini aktif (vault/env) untuk loop proaktif."
                            )
                        proactive_model = _main_brain_gemini_model()
                        resp = await p_client.aio.models.generate_content(
                            model=proactive_model,
                            contents=[
                                types.Content(
                                    role="user",
                                    parts=[
                                        types.Part.from_text(text=proactive_eval_prompt)
                                    ],
                                )
                            ],
                        )
                        token_usage.from_gemini_response(
                            resp,
                            model=proactive_model,
                            key_id=p_key_id,
                            key_label=p_key_label or "gemini-env",
                            context="proactive",
                        )

                        reply_text = (resp.text or "").strip()
                        config["last_ping_date"] = today_str
                        config["pings_today"] = pings_today + 1

                        if (
                            reply_text
                            and "NO_ACTION" not in reply_text.upper()
                            and len(reply_text) > 10
                        ):
                            logger.info(
                                f"Proactive agent initiated autonomous message to user {target_user}"
                            )
                            await safe_send_message(
                                application,
                                target_user,
                                f"✨ **[INISIATIF MANDIRI ALFA]**\n\n{reply_text}",
                            )
                            await database.save_chat_message(
                                target_user,
                                "model",
                                f"[Inisiatif Mandiri]: {reply_text}",
                            )

                            config["last_ping_time"] = now_dt.isoformat()

                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, indent=2)

        except Exception as e:
            logger.error(f"Error in proactive ambient loop: {e}")
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                cycle_backoff = 3600
                logger.warning(
                    "Kuota model habis (429) -> loop proaktif tidur 1 jam agar chat utama tetap punya jatah."
                )

        await asyncio.sleep(cycle_backoff)


async def proactive_ecosystem_watchdog_loop(application: Application):
    """
    Background watchdog that ensures wa-sheets-bot is automatically kept alive
    and immediately alerts Telegram if WhatsApp logs out.
    """
    logger.info("📱 WhatsApp Sheets Bot Ecosystem Watchdog started.")
    import socket

    def is_internet_connected():
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=3)
            return True
        except OSError:
            return False

    last_known_auth_status = "UNKNOWN"
    status_file = os.path.expanduser("~/.alfa/wa_status.json")
    allowed_env = os.getenv("ALLOWED_USER_IDS", "").strip()
    primary_uid = int(allowed_env.split(",")[0].strip()) if allowed_env else None

    while True:
        try:
            online = await asyncio.to_thread(is_internet_connected)
            if online:
                if os.name != "nt":
                    res = await asyncio.to_thread(
                        lambda: subprocess.run(
                            [
                                "systemctl",
                                "--user",
                                "is-active",
                                "wa-sheets-bot.service",
                            ],
                            capture_output=True,
                            text=True,
                        )
                    )
                    state = res.stdout.strip()
                    if state in ["inactive", "failed"]:
                        logger.info(
                            "🌐 Internet connected & wa-sheets-bot is offline. Auto-starting wa-sheets-bot.service..."
                        )
                        await asyncio.to_thread(
                            lambda: subprocess.run(
                                [
                                    "systemctl",
                                    "--user",
                                    "start",
                                    "wa-sheets-bot.service",
                                ],
                                capture_output=True,
                                text=True,
                            )
                        )

                if os.path.exists(status_file) and primary_uid:
                    try:
                        with open(status_file, "r") as f:
                            wa_data = json.load(f)
                        current_status = wa_data.get("status", "UNKNOWN")
                        qr_str = wa_data.get("qr", "")

                        if last_known_auth_status in [
                            "READY",
                            "AUTHENTICATED",
                        ] and current_status in [
                            "QR_READY",
                            "LOGGED_OUT",
                            "DISCONNECTED",
                        ]:
                            logger.warning(
                                f"🚨 WhatsApp logged out! Sending instant alarm to Telegram user {primary_uid}..."
                            )
                            alarm_text = (
                                "🚨 **ALARM: WhatsApp Web Logout / Sesi Terputus!**\n\n"
                                "Bot mendeteksi sesi WhatsApp kamu telah keluar (*logged out*).\n"
                                "📲 **QR Code baru telah siap!** Silakan scan QR code di atas atau buka di browser:\n"
                                "👉 [http://localhost:8080](http://localhost:8080) (Tab Services Hub)\n\n"
                                "Ketik `/wa` untuk kontrol penuh."
                            )
                            if qr_str:
                                import qrcode

                                img = qrcode.make(qr_str)
                                import io

                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                buf.seek(0)
                                await application.bot.send_photo(
                                    chat_id=primary_uid,
                                    photo=buf,
                                    caption=alarm_text,
                                    parse_mode="Markdown",
                                )
                            else:
                                await application.bot.send_message(
                                    chat_id=primary_uid,
                                    text=alarm_text,
                                    parse_mode="Markdown",
                                )

                        last_known_auth_status = current_status
                    except Exception as e:
                        logger.error(f"Error checking WA status in watchdog: {e}")

        except Exception as e:
            logger.error(f"Ecosystem watchdog error: {e}")

        await asyncio.sleep(15)
