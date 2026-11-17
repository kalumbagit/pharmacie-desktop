"""Gestion des utilisateurs (réservée aux détenteurs de `users.manage`)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.core.database import transaction
from app.core.errors import BusinessRuleError, ValidationError
from app.core.security import (
    Permission,
    UserContext,
    generate_temporary_password,
    hash_password,
    validate_identifiant,
    validate_name,
    validate_password_policy,
)
from app.models import Role, User
from app.repositories import AuditRepository, UserRepository

@dataclass(frozen=True)
class CreatedUser:
    user: User
    temporary_password: str  # à communiquer à l'utilisateur, jamais stocké en clair


class UserService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._users = UserRepository(conn)
        self._audit = AuditRepository(conn)

    def list_users(self, ctx: UserContext) -> list[User]:
        ctx.require(Permission.USERS_MANAGE)
        return self._users.list_all()

    def list_roles(self, ctx: UserContext) -> list[Role]:
        ctx.require(Permission.USERS_MANAGE)
        return self._users.list_roles()

    def create_user(
        self,
        ctx: UserContext,
        *,
        identifiant: str,
        nom: str,
        prenom: str,
        role_code: str,
        password: str | None = None,
    ) -> CreatedUser:
        ctx.require(Permission.USERS_MANAGE)
        identifiant = validate_identifiant(identifiant)
        nom = validate_name(nom, "Nom")
        prenom = validate_name(prenom, "Prénom")
        if password is not None:
            validate_password_policy(password, identifiant)
        temporary = password or generate_temporary_password()

        with transaction(self._conn):
            role = self._users.get_role_by_code(role_code)
            if role is None:
                raise ValidationError("Rôle inconnu.")
            if self._users.get_by_identifiant(identifiant) is not None:
                raise BusinessRuleError("Cet identifiant est déjà utilisé.")
            user_id = self._users.insert(
                identifiant=identifiant,
                nom=nom,
                prenom=prenom,
                password_hash=hash_password(temporary),
                role_id=role.id,
                must_change_password=True,
                created_by=ctx.user_id,
            )
            self._audit.add(
                user_id=ctx.user_id,
                action="USER_CREATED",
                entity_type="user",
                entity_id=user_id,
                details={"identifiant": identifiant, "role": role.code},
            )
            user = self._users.get_by_id(user_id)
        assert user is not None
        return CreatedUser(user=user, temporary_password=temporary)

    def update_user(
        self, ctx: UserContext, user_id: int, *, nom: str, prenom: str, role_code: str
    ) -> User:
        ctx.require(Permission.USERS_MANAGE)
        nom = validate_name(nom, "Nom")
        prenom = validate_name(prenom, "Prénom")
        with transaction(self._conn):
            target = self._require_user(user_id)
            role = self._users.get_role_by_code(role_code)
            if role is None:
                raise ValidationError("Rôle inconnu.")
            if (
                target.is_active
                and target.role_code == "ADMIN"
                and role.code != "ADMIN"
                and self._users.count_active_admins(exclude_user_id=target.id) == 0
            ):
                raise BusinessRuleError(
                    "Impossible de retirer le rôle du dernier administrateur actif."
                )
            self._users.update_profile(user_id, nom, prenom, role.id)
            self._audit.add(
                user_id=ctx.user_id,
                action="USER_UPDATED",
                entity_type="user",
                entity_id=user_id,
                details={"role_avant": target.role_code, "role_apres": role.code},
            )
            updated = self._users.get_by_id(user_id)
        assert updated is not None
        return updated

    def set_active(self, ctx: UserContext, user_id: int, active: bool) -> User:
        ctx.require(Permission.USERS_MANAGE)
        with transaction(self._conn):
            target = self._require_user(user_id)
            if not active:
                if user_id == ctx.user_id:
                    raise BusinessRuleError("Vous ne pouvez pas désactiver votre propre compte.")
                if (
                    target.role_code == "ADMIN"
                    and target.is_active
                    and self._users.count_active_admins(exclude_user_id=target.id) == 0
                ):
                    raise BusinessRuleError(
                        "Impossible de désactiver le dernier administrateur actif."
                    )
            self._users.set_active(user_id, active)
            self._audit.add(
                user_id=ctx.user_id,
                action="USER_REACTIVATED" if active else "USER_DEACTIVATED",
                entity_type="user",
                entity_id=user_id,
            )
            updated = self._users.get_by_id(user_id)
        assert updated is not None
        return updated

    def reset_password(self, ctx: UserContext, user_id: int, password: str | None = None) -> str:
        """Réinitialise le mot de passe ; l'utilisateur devra le changer à la connexion."""
        ctx.require(Permission.USERS_MANAGE)
        with transaction(self._conn):
            target = self._require_user(user_id)
            if password is not None:
                validate_password_policy(password, target.identifiant)
            temporary = password or generate_temporary_password()
            self._users.set_password(user_id, hash_password(temporary), True)
            self._audit.add(
                user_id=ctx.user_id,
                action="USER_PASSWORD_RESET",
                entity_type="user",
                entity_id=user_id,
            )
        return temporary

    def _require_user(self, user_id: int) -> User:
        user = self._users.get_by_id(user_id)
        if user is None:
            raise BusinessRuleError("Utilisateur introuvable.")
        return user
