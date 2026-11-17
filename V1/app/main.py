"""Point d'entrée : python -m app.main"""

from __future__ import annotations

import dataclasses
import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.config import Settings, configure_logging
from app.core.database import MigrationError, connect, migrate
from app.services.app_settings import AppSettingsService
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme

logger = logging.getLogger(__name__)


def main() -> int:
    settings = Settings.load()
    settings.ensure_dirs()
    configure_logging(settings.log_dir)

    qt_app = QApplication(sys.argv)
    apply_theme(qt_app)

    conn = connect(settings.db_path)
    try:
        migrate(conn)
    except MigrationError as exc:
        logger.exception("Échec de l'initialisation de la base")
        QMessageBox.critical(None, "Erreur de base de données", str(exc))
        conn.close()
        return 1

    # Dossier des documents choisi dans « Paramètres » (prioritaire sur le dossier par défaut).
    settings = dataclasses.replace(
        settings, documents_dir=AppSettingsService(conn).documents_dir(settings.documents_dir)
    )
    settings.ensure_dirs()

    window = MainWindow(settings, conn)
    window.show()
    code = qt_app.exec()
    conn.close()
    return code


if __name__ == "__main__":
    sys.exit(main())