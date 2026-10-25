"""Linux desktop software installer, updater, and package conflict resolver."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.AppManager")


def _sanitize_app_name(filename: str) -> str:
    """Bersihkan nama file dari versi, arsitektur, dan ekstensi untuk nama binari bersih."""
    base = Path(filename).name
    # Hilangkan ekstensi umum
    for ext in (".AppImage", ".appimage", ".bin", ".deb", ".tar.gz", ".tar.xz"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    # Hilangkan pola versi seperti -0.7.0, _1.2.3, -linux-x86_64, dll.
    base = re.sub(
        r"[-_](?:linux|x86_64|amd64|x64|i386|arm64|aarch64)", "", base, flags=re.I
    )
    base = re.sub(r"[-_]v?\d+(?:\.\d+)+(?:[-_][a-zA-Z0-9]+)?", "", base)
    return base.strip("-_ ") or "app"


def _find_matching_app_id(target_name: str) -> str | None:
    """Cari app ID resmi (misal ai.storyteller.artcraft-launcher) di direktori aplikasi desktop."""
    search_dirs = [
        Path.home() / ".local/share/applications",
        Path("/usr/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local/share/flatpak/exports/share/applications",
    ]
    target_clean = target_name.lower().replace("-", "").replace("_", "")
    for d in search_dirs:
        if not d.exists():
            continue
        try:
            for p in d.glob("*.desktop"):
                stem_clean = p.stem.lower().replace("-", "").replace("_", "")
                if target_clean in stem_clean or stem_clean.endswith(target_clean):
                    return p.stem
        except OSError:
            continue
    return None


def _clean_flatpak_conflicts(app_id_or_name: str) -> list[str]:
    """Cari dan uninstall paket Flatpak lama yang berkonflik jika ada."""
    removed: list[str] = []
    try:
        res = subprocess.run(
            ["flatpak", "list", "--columns=application"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return removed

        installed_apps = [
            line.strip() for line in res.stdout.splitlines() if line.strip()
        ]
        for app in installed_apps:
            # Cocokkan nama aplikasi atau ID
            if app_id_or_name in app or app in app_id_or_name:
                logger.info(f"Mendeteksi konflik Flatpak: {app}. Mencoba uninstall...")
                # Coba uninstall dari system & user
                sub_res = subprocess.run(
                    ["flatpak", "uninstall", "--system", app, "-y"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if sub_res.returncode == 0:
                    removed.append(f"flatpak:system:{app}")
                else:
                    user_res = subprocess.run(
                        ["flatpak", "uninstall", "--user", app, "-y"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if user_res.returncode == 0:
                        removed.append(f"flatpak:user:{app}")
    except (OSError, subprocess.SubprocessError) as err:
        logger.warning(f"Gagal memeriksa/menghapus Flatpak: {err}")
    return removed


def _kill_running_instances(target_name: str, app_id: str | None = None) -> list[int]:
    """Hentikan proses lama aplikasi yang sedang menggantung di layar."""
    killed_pids: list[int] = []
    names_to_check = [target_name]
    if app_id and app_id != target_name:
        names_to_check.append(app_id)
        # Ambil bagian akhir app_id jika ada titik (misal ai.storyteller.artcraft-launcher -> artcraft-launcher)
        if "." in app_id:
            names_to_check.append(app_id.split(".")[-1])

    for nm in names_to_check:
        try:
            # Cari proses langsung
            res = subprocess.run(
                ["pgrep", "-f", nm],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                pid_str = line.strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid != os.getpid():
                        try:
                            os.kill(pid, 15)  # SIGTERM
                            killed_pids.append(pid)
                        except OSError:
                            pass
        except (OSError, subprocess.SubprocessError):
            continue
    return killed_pids


@register_tool(category="media")
def install_or_update_desktop_app(
    file_path: str,
    target_name: str | None = None,
    app_id: str | None = None,
    clean_package_conflicts: bool = True,
    kill_old_process: bool = True,
) -> dict[str, Any]:
    """Pasang atau perbarui aplikasi desktop Linux (AppImage, binary ELF, atau .deb) ke sistem.

    Menangani siklus pembaruan secara tuntas:
    1. Menyalin dan memberikan hak akses eksekusi (+x) ke ~/.local/bin/.
    2. Mendeteksi & menghapus konflik paket lama (seperti versi Flatpak usang).
    3. Mendaftarkan dan menstandarkan shortcut desktop (.desktop) di ~/.local/share/applications/
       serta membersihkan duplikat/entri usang.
    4. Memperbarui database aplikasi GNOME/XDG (update-desktop-database).
    5. Menutup jendela/proses lama yang menggantung agar versi baru langsung aktif.
    6. Memverifikasi versi instalasi akhir (--version).

    Args:
        file_path: Path berkas installer/AppImage/binari (misal: '~/Dokumen/artcraft-launcher-0.7.0.AppImage').
        target_name: Nama binari tujuan di ~/.local/bin/ (opsional; otomatis diambil dari nama bersih file).
        app_id: ID aplikasi resmi desktop (misal: 'ai.storyteller.artcraft-launcher'). Opsional; otomatis dideteksi.
        clean_package_conflicts: Jika True, hapus paket usang (misal Flatpak lama) yang membajak peluncur aplikasi.
        kill_old_process: Jika True, matikan proses lama yang sedang berjalan di desktop.
    """
    expanded_path = os.path.expanduser(file_path.strip())
    src = Path(expanded_path)
    if not src.exists():
        return {
            "status": "error",
            "message": f"Berkas sumber '{file_path}' tidak ditemukan di sistem.",
        }

    # 1. Bersihkan nama target & direktori binari
    clean_name = target_name.strip() if target_name else _sanitize_app_name(src.name)
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest_binary = bin_dir / clean_name

    # 2. Deteksi App ID resmi jika belum diberikan
    detected_id = app_id.strip() if app_id else _find_matching_app_id(clean_name)
    if not detected_id:
        detected_id = f"custom.{clean_name}"

    # 3. Hentikan proses lama jika diminta
    killed_pids: list[int] = []
    if kill_old_process:
        killed_pids = _kill_running_instances(clean_name, detected_id)

    # 4. Bersihkan konflik paket (Flatpak) jika diminta
    conflicts_removed: list[str] = []
    if clean_package_conflicts:
        conflicts_removed = _clean_flatpak_conflicts(detected_id)

    # 5. Salin binari & set executable
    try:
        shutil.copy2(src, dest_binary)
        os.chmod(dest_binary, 0o755)  # nosec B103
    except OSError as err:
        return {
            "status": "error",
            "message": f"Gagal menyalin atau menyetel hak eksekusi ke '{dest_binary}': {err}",
        }

    # 6. Jalankan pemicu integrasi mandiri jika ada (banyak AppImage membuat desktop entry saat run)
    version_output = "unknown"
    try:
        ver_res = subprocess.run(
            [str(dest_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ver_res.returncode == 0:
            version_output = (ver_res.stdout or ver_res.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        pass

    # 7. Konfigurasi Desktop Entry
    app_dir = Path.home() / ".local/share/applications"
    app_dir.mkdir(parents=True, exist_ok=True)
    target_desktop = app_dir / f"{detected_id}.desktop"

    # Jika .desktop belum ada atau perlu diperbarui
    pretty_name = clean_name.replace("-", " ").replace("_", " ").title()
    desktop_content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={pretty_name}\n"
        f"Comment=Installed via ALFA AppManager\n"
        f"Exec={dest_binary}\n"
        f"Icon={detected_id}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "StartupNotify=true\n"
    )

    if not target_desktop.exists():
        try:
            target_desktop.write_text(desktop_content, encoding="utf-8")
        except OSError as err:
            logger.warning(f"Gagal menulis desktop entry {target_desktop}: {err}")
    else:
        # Perbaiki Exec line agar tidak ada tanda kutip rusak
        try:
            current_text = target_desktop.read_text(encoding="utf-8")
            if (
                f'Exec="{dest_binary}"' in current_text
                or f"Exec={dest_binary}" not in current_text
            ):
                new_text = re.sub(
                    r"^Exec=.*$",
                    f"Exec={dest_binary}",
                    current_text,
                    flags=re.MULTILINE,
                )
                target_desktop.write_text(new_text, encoding="utf-8")
        except OSError:
            pass

    # 8. Bersihkan entri duplikat yang membingungkan GNOME (misal app-name.desktop generik)
    redundant_desktop = app_dir / f"{clean_name}.desktop"
    if redundant_desktop.exists() and redundant_desktop != target_desktop:
        try:
            redundant_desktop.unlink()
        except OSError:
            pass

    # 9. Update database desktop sistem
    try:
        subprocess.run(
            ["update-desktop-database", str(app_dir)],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "status": "success",
        "message": f"Aplikasi '{clean_name}' berhasil dipasang/diperbarui.",
        "binary_path": str(dest_binary),
        "desktop_entry": str(target_desktop),
        "version": version_output,
        "conflicts_removed": conflicts_removed,
        "processes_killed": killed_pids,
    }
