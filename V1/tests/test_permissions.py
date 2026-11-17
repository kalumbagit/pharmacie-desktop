import sqlite3

from app.core.security import Permission


def _codes_for(db: sqlite3.Connection, role: str) -> set[str]:
    rows = db.execute(
        "SELECT p.code FROM role_permissions rp "
        "JOIN roles r ON r.id = rp.role_id JOIN permissions p ON p.id = rp.permission_id "
        "WHERE r.code = ?",
        (role,),
    )
    return {r[0] for r in rows}


def test_permission_enum_matches_database(db: sqlite3.Connection) -> None:
    in_db = {r[0] for r in db.execute("SELECT code FROM permissions")}
    assert in_db == {p.value for p in Permission}


def test_admin_has_every_permission(db: sqlite3.Connection) -> None:
    assert _codes_for(db, "ADMIN") == {p.value for p in Permission}


def test_cashier_is_restricted(db: sqlite3.Connection) -> None:
    codes = _codes_for(db, "CAISSIER")
    assert Permission.SALES_CREATE in codes
    assert Permission.PAYMENTS_RECORD in codes
    assert Permission.USERS_MANAGE not in codes
    assert Permission.PURCHASES_CREATE not in codes
    assert Permission.SALES_VIEW_ALL not in codes
    assert Permission.PRICE_EDIT not in codes


def test_pharmacist_cannot_administer(db: sqlite3.Connection) -> None:
    codes = _codes_for(db, "PHARMACIEN")
    assert Permission.STOCK_ADJUST in codes
    assert Permission.USERS_MANAGE not in codes
    assert Permission.SETTINGS_EDIT not in codes
    assert Permission.ACCOUNTING_VIEW not in codes
