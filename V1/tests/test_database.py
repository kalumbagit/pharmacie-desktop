import sqlite3
from pathlib import Path

import pytest

from app.core.database import MigrationError, current_version, migrate, transaction


def test_foreign_keys_are_enabled(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_transaction_commits(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE t (x INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_transaction_rolls_back_on_error(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("échec simulé")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_nested_transaction_rolls_back_only_inner(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE t (x INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(RuntimeError), transaction(conn):
            conn.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("échec interne")
    assert [r[0] for r in conn.execute("SELECT x FROM t")] == [1]


def test_migrate_applies_baseline_and_is_idempotent(conn: sqlite3.Connection) -> None:

    assert migrate(conn) == [1, 2, 3]
    assert current_version(conn) == 3
    assert migrate(conn) == []
    devise = conn.execute("SELECT valeur FROM app_settings WHERE cle = 'devise'").fetchone()
    assert devise["valeur"] == "FCFA"


def test_failed_migration_is_fully_rolled_back(conn: sqlite3.Connection, tmp_path: Path) -> None:
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_ok.sql").write_text("CREATE TABLE a (id INTEGER);")
    (folder / "0002_ko.sql").write_text(
        "CREATE TABLE b (id INTEGER);\nINSERT INTO inconnue VALUES (1);"
    )

    with pytest.raises(MigrationError):
        migrate(conn, folder)

    assert current_version(conn) == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables
    assert "b" not in tables


def test_modified_migration_is_detected(conn: sqlite3.Connection, tmp_path: Path) -> None:
    folder = tmp_path / "migrations"
    folder.mkdir()
    file = folder / "0001_init.sql"
    file.write_text("CREATE TABLE a (id INTEGER);")
    migrate(conn, folder)

    file.write_text("CREATE TABLE a (id INTEGER, extra TEXT);")
    with pytest.raises(MigrationError):
        migrate(conn, folder)