import sqlite3

import pytest

from app.core.security import UserContext
from app.core.security import hash_password, verify_password
from app.core.security import Permission
from app.services.auth import (
    LOCK_MINUTES,
    MAX_FAILED_ATTEMPTS,
    AuthService,
)
from app.services.users import UserService
from app.core.errors import (
    AccountDisabledError,
    AccountLockedError,
    AuthenticationError,
    BusinessRuleError,
    MustChangePasswordError,
    ValidationError,
)
from tests.conftest import FakeClock, make_active_user


def test_first_admin_can_only_be_created_once(auth: AuthService) -> None:
    assert auth.needs_setup()
    auth.create_first_admin("admin", "Dupont", "Marie", "Admin2026x")
    assert not auth.needs_setup()
    with pytest.raises(BusinessRuleError):
        auth.create_first_admin("autre", "X", "Y", "Admin2026x")


def test_passwords_are_never_stored_in_clear(
    db: sqlite3.Connection, admin_ctx: UserContext
) -> None:
    stored = db.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored != "Admin2026x"
    assert stored.startswith("$2")
    assert verify_password("Admin2026x", stored)
    assert not verify_password("mauvais", stored)
    assert hash_password("abc12345") != hash_password("abc12345")  # sel aléatoire


def test_login_success_loads_permissions(admin_ctx: UserContext) -> None:
    assert admin_ctx.role_code == "ADMIN"
    assert admin_ctx.has(Permission.USERS_MANAGE)
    assert not admin_ctx.must_change_password


def test_wrong_password_and_unknown_user_share_same_message(
    auth: AuthService, admin_ctx: UserContext
) -> None:
    with pytest.raises(AuthenticationError) as wrong:
        auth.login("admin", "faux")
    with pytest.raises(AuthenticationError) as unknown:
        auth.login("inconnu", "faux")
    assert str(wrong.value) == str(unknown.value)


def test_account_locks_after_repeated_failures_then_unlocks(
    auth: AuthService, admin_ctx: UserContext, clock: FakeClock
) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            auth.login("admin", "faux")
    with pytest.raises(AccountLockedError):
        auth.login("admin", "Admin2026x")  # même avec le bon mot de passe

    clock.advance(minutes=LOCK_MINUTES + 1)
    assert auth.login("admin", "Admin2026x").user_id == admin_ctx.user_id


def test_disabled_account_cannot_login(
    auth: AuthService, users: UserService, admin_ctx: UserContext
) -> None:
    caissier = make_active_user(auth, users, admin_ctx, "caisse1", "CAISSIER")
    users.set_active(admin_ctx, caissier.user_id, False)
    with pytest.raises(AccountDisabledError):
        auth.login("caisse1", "NouveauPass1")
    users.set_active(admin_ctx, caissier.user_id, True)
    assert auth.login("caisse1", "NouveauPass1").user_id == caissier.user_id


def test_first_login_forces_password_change(
    auth: AuthService, users: UserService, admin_ctx: UserContext
) -> None:
    created = users.create_user(
        admin_ctx, identifiant="pharma1", nom="Test", prenom="User", role_code="PHARMACIEN"
    )
    ctx = auth.login("pharma1", created.temporary_password)
    assert ctx.must_change_password
    with pytest.raises(MustChangePasswordError):  # bloqué au niveau métier
        ctx.require(Permission.SALES_CREATE)

    new_ctx = auth.change_password(ctx, created.temporary_password, "NouveauPass1")
    assert not new_ctx.must_change_password
    new_ctx.require(Permission.SALES_CREATE)

    with pytest.raises(AuthenticationError):  # l'ancien mot de passe ne marche plus
        auth.login("pharma1", created.temporary_password)


def test_change_password_rejects_wrong_old_and_weak_new(
    auth: AuthService, admin_ctx: UserContext
) -> None:
    with pytest.raises(AuthenticationError):
        auth.change_password(admin_ctx, "faux", "NouveauPass1")
    with pytest.raises(ValidationError):
        auth.change_password(admin_ctx, "Admin2026x", "court1")
    with pytest.raises(ValidationError):
        auth.change_password(admin_ctx, "Admin2026x", "uniquementdeslettres")
    with pytest.raises(BusinessRuleError):
        auth.change_password(admin_ctx, "Admin2026x", "Admin2026x")


def test_audit_log_is_immutable(db: sqlite3.Connection, admin_ctx: UserContext) -> None:
    actions = {r[0] for r in db.execute("SELECT action FROM audit_log")}
    assert {"FIRST_ADMIN_CREATED", "LOGIN"} <= actions
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE audit_log SET action = 'X'")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM audit_log")
