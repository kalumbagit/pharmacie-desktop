"""Configuration de l'application et journalisation technique."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def _app_base_dir() -> Path:
    """Dossier de référence des données (base, logs, documents).

    - Exécutable PyInstaller (onefile) : dossier utilisateur
      ``%LOCALAPPDATA%\\Pharmacie`` (Windows). Les données y sont créées directement,
      sans tester le dossier de l'.exe. ``__file__`` pointerait vers un dossier
      temporaire supprimé à la fermeture : les données seraient perdues.
    - Développement : racine du projet.
    """
    if FROZEN:
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(root) / "Pharmacie"
    return Path(__file__).resolve().parents[2]


BASE_DIR = _app_base_dir()


@dataclass(frozen=True)
class Settings:
    app_name: str
    data_dir: Path
    db_path: Path
    backup_dir: Path
    log_dir: Path
    currency: str
    # Factures, reçus, fiches d'inventaire, logo.png (filigrane). Défaut : <projet>/documents.
    documents_dir: Path = BASE_DIR / "documents"

    @classmethod
    def load(cls) -> Settings:
        """Charge la configuration. PHARMACIE_DATA_DIR permet de déplacer les données."""
        data_dir = Path(os.environ.get("PHARMACIE_DATA_DIR", BASE_DIR / "data"))
        documents_dir = Path(os.environ.get("PHARMACIE_DOCUMENTS_DIR", BASE_DIR / "documents"))
        return cls(
            app_name="Pharmacie",
            data_dir=data_dir,
            db_path=data_dir / "pharmacie.db",
            backup_dir=data_dir / "backups",
            log_dir=data_dir / "logs",
            currency="FCFA",
            documents_dir=documents_dir,
        )

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.backup_dir, self.log_dir, self.documents_dir):
            directory.mkdir(parents=True, exist_ok=True)


def configure_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)