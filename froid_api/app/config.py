"""
Module de configuration de l'application.
Charge les paramètres depuis les variables d'environnement (ou un fichier .env)
avec des valeurs par défaut conformes aux spécifications du projet.
"""

import os
from pathlib import Path


def _load_env_file(env_path: Path) -> None:
    """Charge un fichier .env dans os.environ si le fichier existe."""
    if not env_path.is_file():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


# Recherche du fichier .env à la racine du projet froid_api ou dans le répertoire courant
_current_dir = Path(__file__).resolve().parent
_load_env_file(_current_dir.parent / ".env")
_load_env_file(Path(".env"))


class Settings:
    """Paramètres globaux de l'application."""

    def __init__(self) -> None:
        # Firebase Realtime Database
        raw_firebase = os.getenv(
            "FIREBASE_URL",
            "https://chaine-du-froid-default-rtdb.europe-west1.firebasedatabase.app",
        )
        self.FIREBASE_URL: str = raw_firebase.rstrip("/")

        # MongoDB
        self.MONGO_URL: str = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        self.MONGO_DB: str = os.getenv("MONGO_DB", "chaine_froid")
        self.MONGO_TIMEOUT_MS: int = int(os.getenv("MONGO_TIMEOUT_MS", "2000"))

        # Seuils thermiques (°C)
        self.TEMP_MIN: float = float(os.getenv("TEMP_MIN", "2.0"))
        self.TEMP_MAX: float = float(os.getenv("TEMP_MAX", "8.0"))

        # Détection d'alertes
        self.ALERT_MIN_READINGS: int = int(os.getenv("ALERT_MIN_READINGS", "3"))

        # Intervalles et délais (secondes)
        self.POLL_SECONDS: float = float(os.getenv("POLL_SECONDS", "2.0"))
        self.STALE_SECONDS: float = float(os.getenv("STALE_SECONDS", "30.0"))


settings = Settings()
