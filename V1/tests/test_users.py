import sqlite3

import pytest

from app.core.security import UserContext
from app.services.auth import AuthService
from app.services.users import UserService
from app.core.errors import BusinessRuleError, PermissionDeniedError
from tests.conftest import make_active_user


def test_only_admin_can_manage_users(
    auth: AuthService, users: UserService, admin_ctx: UserContext
) -> None:
    caissier = make_active_user(auth, users, admin_ctx, "caisse1", "CAISSIER")
    pharmacien = make_active_user(auth, users, admin_ctx, "pharma1", "PHARMACIEN")
    for ctx in (caissier, pharmacien):
        with pytest.raises(PermissionDeniedError):
            users.list_users(ctx)
        with pytest.raises(PermissionDeniedError):
            users.create_user(ctx, identifiant="x1234", nom="A", prenom="B", role_code="CAISSIER")


def test_identifiant_is_unique_case_insensitive(users: UserService, admin_ctx: UserContext) -> None:
    users.create_user(admin_ctx, identifiant="Jean", nom="A", prenom="B", role_code="CAISSIER")
    with pytest.raises(BusinessRuleError):
        users.create_user(admin_ctx, identifiant="jean", nom="C", prenom="D", role_code="CAISSIER")


def test_admin_cannot_deactivate_self(users: UserService, admin_ctx: UserContext) -> None:
    with pytest.raises(BusinessRuleError):
        users.set_active(admin_ctx, admin_ctx.user_id, False)


def test_last_active_admin_cannot_lose_admin_role(
    users: UserService, admin_ctx: UserContext
) -> None:
    with pytest.raises(BusinessRuleError):
        users.update_user(
            admin_ctx, admin_ctx.user_id, nom="Dupont", prenom="Marie", role_code="PHARMACIEN"
        )


def test_admin_can_demote_another_admin(users: UserService, admin_ctx: UserContext) -> None:
    second = users.create_user(
        admin_ctx, identifiant="admin2", nom="A", prenom="B", role_code="ADMIN"
    )
    updated = users.update_user(
        admin_ctx, second.user.id, nom="A", prenom="B", role_code="PHARMACIEN"
    )
    assert updated.role_code == "PHARMACIEN"


def test_reset_password_forces_new_change(
    auth: AuthService, users: UserService, admin_ctx: UserContext
) -> None:
    caissier = make_active_user(auth, users, admin_ctx, "caisse1", "CAISSIER")
    temporary = users.reset_password(admin_ctx, caissier.user_id)
    ctx = auth.login("caisse1", temporary)
    assert ctx.must_change_password


def test_user_actions_are_audited(
    db: sqlite3.Connection, users: UserService, admin_ctx: UserContext
) -> None:
    created = users.create_user(
        admin_ctx, identifiant="caisse1", nom="A", prenom="B", role_code="CAISSIER"
    )
    users.set_active(admin_ctx, created.user.id, False)
    actions = [r[0] for r in db.execute("SELECT action FROM audit_log ORDER BY id")]
    assert "USER_CREATED" in actions
    assert "USER_DEACTIVATED" in actions


def test_users_cannot_be_deleted(db: sqlite3.Connection, admin_ctx: UserContext) -> None:
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM users")
