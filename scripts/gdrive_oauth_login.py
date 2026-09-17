#!/usr/bin/env python3
"""
One-time Google Drive OAuth login for ALFA.

Run this ONCE from your desktop terminal:
    ./venv/bin/python scripts/gdrive_oauth_login.py

A browser will open; choose your Google account and allow access.
The token is saved to gdrive_oauth_token.json and reused automatically
by the bot & dashboard afterwards (refreshable, no re-login needed).

Prerequisite: gdrive_oauth_client_secret.json in the project root
(OAuth Client ID -> Desktop app from Google Cloud Console).
"""

import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

import tools  # noqa: E402


def main():
    secret = os.path.join(PROJECT_DIR, "gdrive_oauth_client_secret.json")
    if not os.path.exists(secret):
        print("❌ File client secret tidak ditemukan:", secret)
        print()
        print("Langkah membuatnya (±2 menit):")
        print("  1. Buka https://console.cloud.google.com/apis/credentials")
        print("     (pakai project yang sama dengan service account Drive Anda)")
        print("  2. 'Create Credentials' > 'OAuth client ID'")
        print("  3. Application type: Desktop app > Create")
        print("  4. Klik 'Download JSON', simpan sebagai:")
        print("     " + secret)
        print("  5. Menu 'OAuth consent screen' > tab Audience/Testing")
        print("     > tambahkan email Google Anda sebagai Test user")
        print()
        print("Setelah file ada, jalankan lagi perintah ini.")
        sys.exit(1)

    print("🔑 Memulai login OAuth Google Drive...")
    print("   Jika browser tidak terbuka otomatis, salin URL dari bawah ke browser.")
    print()

    res = tools.gdrive_oauth_login(port=8999, wait_timeout=300)

    if res["status"] == "success":
        st = tools.gdrive_status()
        user = (st.get("user") or {}).get("emailAddress", "?")
        print()
        print("✅ BERHASIL! Upload Drive kini memakai akun:", user)
        print("   Token tersimpan di:", res.get("token_file"))
        print("   Bot & Dashboard otomatis memakainya tanpa restart.")
        sys.exit(0)
    else:
        print()
        print("❌ GAGAL:", res.get("message"))
        sys.exit(1)


if __name__ == "__main__":
    main()
