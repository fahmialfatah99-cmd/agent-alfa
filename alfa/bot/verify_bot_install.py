#!/usr/bin/env python3
"""
Post-install verification untuk patch ALFA bot files.

Jalankan DI DALAM environment ALFA asli (di mana `import alfa` berhasil):

    cd ~/ALFA && python3 verify_bot_install.py

Exit 0 = semua oke, 1 = ada yang belum beres.
"""
import importlib
import sys
import tempfile

PASS: list[str] = []
FAIL: list[str] = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def hdr(t):
    print("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)


def main():
    print("=" * 70)
    print("ALFA bot — verifikasi install patch")
    print("=" * 70)

    hdr("0. Import semua modul yang dipatch")
    mods = {}
    for name in (
        "alfa.bot.helpers",
        "alfa.bot.config",
        "alfa.bot.basic_commands",
        "alfa.bot.advanced_commands",
        "alfa.bot.cloud_menu",
        "alfa.bot.commands",
        "alfa.bot.handlers",
    ):
        try:
            mods[name] = importlib.import_module(name)
            check(f"import {name}", True)
        except Exception as e:
            check(f"import {name}", False, f"{type(e).__name__}: {e}")
    if len(mods) < 7:
        print("\nImport gagal — STOP. Sisa tes dilewati.")
        return 1

    helpers = mods["alfa.bot.helpers"]
    config = mods["alfa.bot.config"]
    handlers = mods["alfa.bot.handlers"]
    advanced = mods["alfa.bot.advanced_commands"]

    hdr("1. split_message(): fence code block selalu seimbang")
    bad = 0
    for pad in range(3400, 3960, 7):
        body = "A" * pad + "\n```\n" + "B" * 80 + "\n```\ntail"
        for c in helpers.split_message(body, max_length=3900):
            if c.count("```") % 2 != 0:
                bad += 1
    check("0 chunk dengan fence tak seimbang", bad == 0, f"found {bad}")

    hdr("2. Model Gemini default bukan yang deprecated")
    check("default bukan gemini-3.5-flash", config.GEMINI_MODEL != "gemini-3.5-flash",
          config.GEMINI_MODEL)

    hdr("3. _execute_document_batch punya except (user tidak diam)")
    import inspect
    src = inspect.getsource(handlers._execute_document_batch)
    check("ada blok except", "except _HANDLER_ERR" in src)

    hdr("4. Callback 'perm|*' selalu di-answer()")
    src = inspect.getsource(handlers.handle_callback_query)
    head = src.split("await query.answer()")[0]
    check("perm| return SETELAH answer()", "await query.answer()" not in head)

    hdr("5. Koneksi sqlite3 ditutup eksplisit")
    src = inspect.getsource(handlers._get_or_recover_recent_doc)
    check("ada conn.close()", "conn.close()" in src)

    hdr("6. advanced_commands: akses dict aman")
    src = inspect.getsource(advanced.skills_command)
    check("tidak ada subscript langsung", 's["learned_rule"]' not in src)
    src = inspect.getsource(advanced.resume_swarm_command)
    check("resume pakai .get()", 'r.get("updated_at")' in src)

    hdr("7. apex_command: maintenance tidak membekukan event loop")
    src = inspect.getsource(advanced.apex_command)
    check("memakai asyncio.to_thread", "asyncio.to_thread(run_autonomous_apex_maintenance" in src)

    hdr("8. Discord bot module (opsional — skip kalau tidak terpasang)")
    try:
        dbot = importlib.import_module("alfa.bot.discord_bot")
        check("import alfa.bot.discord_bot", True)
        ch = dbot._split("X" * 3000)
        check("tidak ada chunk kosong", all(c.strip() for c in ch), f"lens={[len(c) for c in ch]}")
        check("semua chunk <= 2000", all(len(c) <= 2000 for c in ch), f"lens={[len(c) for c in ch]}")
        src = inspect.getsource(dbot)
        check("konteks voice per-user", "_DISCORD_CMD_CTX: dict[int, dict]" in src)
        check("registry sync pakai list penuh",
              "sync_registry_from_available(list(AVAILABLE_TOOLS))" in src)
    except ModuleNotFoundError:
        check("discord_bot tidak terpasang (lewati)", True, "skip")
    except Exception as e:
        check("import alfa.bot.discord_bot", False, f"{type(e).__name__}: {e}")

    hdr("9. Smoke: bikin build nyata lewat pipeline ALFA")
    try:
        _tools = importlib.import_module("alfa.tools")
        factory = importlib.import_module("alfa.tools.system.software_factory")
        with tempfile.TemporaryDirectory() as tmp:
            r = factory.build_and_verify_fullstack_app(
                app_slug="verify-install-check",
                title="Verify Install",
                frontend_html="<html><body><button onclick=\"alert('hi')\">x</button></body></html>",
                backend_py="print('ok')\n",
                sites_root=tmp,
            )
            e2e = r.get("e2e_verification", {})
            check("build status success", r.get("status") == "success",
                  f"{r.get('status')} / {e2e.get('issues')}")
            check("live HTTP smoke passed", e2e.get("live_http_smoke", {}).get("passed") is True,
                  str(e2e.get("live_http_smoke")))
    except Exception as e:
        check("pipeline software_factory jalan", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("\nFAILURES:")
        for f in FAIL:
            print("  -", f)
        return 1
    print("ALL GREEN — patch terpasang & berfungsi benar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
