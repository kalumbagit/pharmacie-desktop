"""Paramètres de l'application (identité de la pharmacie, taxe, remises, alertes)."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.core.database import transaction
from app.core.errors import ValidationError
from app.core.security import Permission, UserContext
from app.repositories import AuditRepository, SettingsRepository

DOCUMENTS_DIR_KEY = "dossier_documents"


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str  # « text » ou « int »
    maximum: int = 0
    minimum: int = 0
    required: bool = False


FIELDS: tuple[Field, ...] = (
    Field("pharmacie_nom", "Nom de la pharmacie", "text", 80, required=True),
    Field("pharmacie_adresse", "Adresse", "text", 150),
    Field("pharmacie_telephone", "Téléphone", "text", 40),
    Field("pharmacie_mention", "Mention légale (NIU, RCCM...)", "text", 150),
    Field(DOCUMENTS_DIR_KEY, "Dossier des documents (vide = dossier par défaut)", "text", 260),
    Field("taxe_libelle", "Libellé de la taxe", "text", 20, required=True),
    Field("taxe_vente_bp", "Taux de taxe sur les ventes (points de base)", "int", 10000),
    Field("remise_max_pct_ADMIN", "Remise maximale Administrateur (%)", "int", 100),
    Field("remise_max_pct_PHARMACIEN", "Remise maximale Pharmacien (%)", "int", 100),
    Field("remise_max_pct_CAISSIER", "Remise maximale Caissier (%)", "int", 100),
    Field("peremption_alerte_jours", "Alerte de péremption (jours)", "int", 730, minimum=1),
)

_BY_KEY = {f.key: f for f in FIELDS}


class AppSettingsService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._settings = SettingsRepository(conn)
        self._audit = AuditRepository(conn)

    def get_all(self, ctx: UserContext) -> dict[str, str]:
        ctx.require(Permission.SETTINGS_EDIT)
        stored = self._settings.get_all()
        return {f.key: stored.get(f.key, "") for f in FIELDS}

    def documents_dir(self, default: Path) -> Path:
        """Dossier des documents à utiliser : celui des paramètres, sinon `default`.

        Appelé au démarrage, avant toute connexion : aucune permission n'est requise.
        Une valeur vide ou un chemin relatif (donc ambigu) retombe sur `default`."""
        stored = self._settings.get(DOCUMENTS_DIR_KEY, "").strip()
        if not stored:
            return default
        path = Path(stored).expanduser()
        return path if path.is_absolute() else default

    def update(
        self, ctx: UserContext, values: dict[str, str]
    ) -> dict[str, str]:
        ctx.require(Permission.SETTINGS_EDIT)

        cleaned = {
            key: self._clean(key, raw)
            for key, raw in values.items()
        }
        if cleaned.get(DOCUMENTS_DIR_KEY):
            self._check_folder(cleaned[DOCUMENTS_DIR_KEY])

        with transaction(self._conn):
            before = self._settings.get_all()
            changes = {}

            for key, value in cleaned.items():
                if before.get(key) != value:
                    self._settings.set(key, value)
                    changes[key] = [before.get(key), value]

            if changes:
                self._audit.add(
                    user_id=ctx.user_id,
                    action="SETTINGS_UPDATED",
                    entity_type="settings",
                    details=changes,
                )

        return self.get_all(ctx)

    @staticmethod
    def _check_folder(value: str) -> None:
        """Le dossier doit être un chemin complet, créable et accessible en écriture."""
        path = Path(value).expanduser()

        if not path.is_absolute():
            raise ValidationError(
                "Le dossier des documents doit être un chemin complet "
                "(ex. /home/utilisateur/documents ou C:\\Pharmacie\\documents)."
            )

        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValidationError(
                f"Impossible de créer le dossier des documents : {exc.strerror or exc}."
            ) from exc

        if not os.access(path, os.W_OK):
            raise ValidationError(
                "Le dossier des documents n'est pas accessible en écriture."
            )

    @staticmethod
    def _clean(key: str, raw: str) -> str:
        field = _BY_KEY.get(key)

        if field is None:
            raise ValidationError(f"Paramètre inconnu : {key}.")

        value = " ".join(str(raw).split())

        if field.kind == "int":
            if (
                not value.isdigit()
                or not field.minimum <= int(value) <= field.maximum
            ):
                raise ValidationError(
                    f"« {field.label} » doit être un entier entre "
                    f"{field.minimum} et {field.maximum}."
                )

            return str(int(value))

        if field.required and not value:
            raise ValidationError(f"« {field.label} » est obligatoire.")

        if len(value) > field.maximum:
            raise ValidationError(
                f"« {field.label} » est trop long "
                f"({field.maximum} caractères max)."
            )

        return value