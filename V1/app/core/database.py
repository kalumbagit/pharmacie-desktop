"""Base de données : connexion SQLite, transactions et migrations versionnées.

La connexion est en mode autocommit côté Python (isolation_level=None) :
toutes les transactions sont explicites via `transaction()`.

Migrations : fichiers app/migrations/NNNN_description.sql, appliqués dans l'ordre,
chacun dans une transaction. Une migration déjà appliquée ne doit jamais être
modifiée (son empreinte SHA-256 est vérifiée). Pas de BEGIN/COMMIT dans les fichiers.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


# ----------------------------------------------------------------------------
# Connexion et transactions
# ----------------------------------------------------------------------------
def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection]:
    """Transaction atomique. Imbriquable : une transaction interne devient un SAVEPOINT.

    BEGIN IMMEDIATE verrouille l'écriture dès le début, ce qui évite les conflits
    de verrou en milieu d'opération (ex. deux validations de vente simultanées).
    """
    if conn.in_transaction:
        name = f"sp_{uuid.uuid4().hex}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        else:
            conn.execute(f"RELEASE {name}")
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")



# ----------------------------------------------------------------------------
# Migrations
# ----------------------------------------------------------------------------
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(Exception):
    """Erreur de migration (fichier invalide, empreinte modifiée, SQL en échec)."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise MigrationError(f"Nom de migration invalide : {path.name}")
        version = int(match.group(1))
        if version in migrations:
            raise MigrationError(f"Version de migration en double : {version:04d}")
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations[version] = Migration(version, match.group(2), sql, checksum)
    return [migrations[v] for v in sorted(migrations)]


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            checksum   TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_table(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(row["v"])


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Applique les migrations en attente. Retourne les versions appliquées."""
    _ensure_table(conn)
    done = {
        row["version"]: row["checksum"]
        for row in conn.execute("SELECT version, checksum FROM schema_migrations")
    }
    applied: list[int] = []

    for migration in discover(directory):
        if migration.version in done:
            if done[migration.version] != migration.checksum:
                raise MigrationError(
                    f"La migration {migration.version:04d}_{migration.name} a été modifiée "
                    "après son application. Créez une nouvelle migration à la place."
                )
            continue

        logger.info("Application de la migration %04d_%s", migration.version, migration.name)
        try:
            conn.executescript("BEGIN IMMEDIATE;\n" + migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"Échec de la migration {migration.version:04d}_{migration.name} : {exc}"
            ) from exc
        applied.append(migration.version)

    return applied
