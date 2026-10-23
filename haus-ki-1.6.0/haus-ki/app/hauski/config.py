"""Start-Konfiguration aus der Umgebung (/etc/haus-ki/haus-ki.env).

Alles, was Administratoren in der Oberfläche ändern können, liegt in der Datenbank
(siehe settings.py).
"""
import os
from pathlib import Path


class Config:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("HAUSKI_DATA", "/var/lib/haus-ki"))
        self.secret_key = os.environ.get("HAUSKI_SECRET_KEY", "")
        self.base_url = os.environ.get("HAUSKI_BASE_URL", "https://ki.home").rstrip("/")
        self.setup_code = os.environ.get("HAUSKI_SETUP_CODE", "")
        self.bootstrap_file = Path(os.environ.get("HAUSKI_BOOTSTRAP", "/etc/haus-ki/bootstrap.json"))
        self.dev = os.environ.get("HAUSKI_DEV") == "1"
        root = Path(__file__).resolve().parents[2]
        self.static_dir = root / "app" / "static"
        self.agent_dir = root / "install" / "agent"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "haus-ki.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def update_dir(self) -> Path:
        return self.data_dir / "updates"


config = Config()
