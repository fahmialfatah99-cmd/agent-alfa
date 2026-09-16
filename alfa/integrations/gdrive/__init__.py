"""Google Drive & Google Cloud Suite Package."""

from alfa.integrations.gdrive.auth import (
    PROJECT_DIR,
    REPO_ROOT,
    SANDBOX_DIR,
    _detect_gdrive_auth_mode,
    _get_default_gdrive_folder_id,
    _get_gdrive_service,
    gdrive_oauth_exchange_code,
    gdrive_oauth_get_auth_url,
    gdrive_oauth_login,
    gdrive_oauth_logout,
    gdrive_save_oauth_client_secret,
    gdrive_status,
)
from alfa.integrations.gdrive.operations import (
    gdrive_create_folder,
    gdrive_download_file,
    gdrive_list_files,
    gdrive_sync_to_second_brain,
    gdrive_upload_file,
)

__all__ = [
    "PROJECT_DIR",
    "REPO_ROOT",
    "SANDBOX_DIR",
    "_get_default_gdrive_folder_id",
    "_get_gdrive_service",
    "_detect_gdrive_auth_mode",
    "gdrive_oauth_login",
    "gdrive_save_oauth_client_secret",
    "gdrive_oauth_get_auth_url",
    "gdrive_oauth_exchange_code",
    "gdrive_oauth_logout",
    "gdrive_status",
    "gdrive_list_files",
    "gdrive_upload_file",
    "gdrive_download_file",
    "gdrive_create_folder",
    "gdrive_sync_to_second_brain",
]
