"""Authentification : connexion, verrouillage, changement de mot de passe."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from app.core.database import transaction
from app.core.errors import (
    AccountDisabledError,
    AccountLockedError,
    AppError,
    AuthenticationError,
    BusinessRuleError,
)
from app.core.security import (
    UserContext,
    hash_password,
    validate_identifiant,
    validate_name,
    validate_password_policy,
    verify_password,
)
from app.core.utils import from_iso, now_utc, to_iso
from app.models import User
from app.repositories import AuditRepository, UserRepository

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
GENERIC_LOGIN_ERROR = "Identifiant ou mot de passe incorrect."


class AuthService:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], datetime] = now_utc) -> None:
        self._conn = conn
        self._clock = clock
        self._users = UserRepository(conn)
        self._audit = AuditRepository(conn)

    # --- installation initiale -------------------------------------------------
    def needs_setup(self) -> bool:
        return self._users.count() == 0

    def create_first_admin(self, identifiant: str, nom: str, prenom: str, password: str) -> User:
        identifiant = validate_identifiant(identifiant)
        nom = validate_name(nom, "Nom")
        prenom = validate_name(prenom, "Prénom")
        validate_password_policy(password, identifiant)
        with transaction(self._conn):
            if self._users.count() > 0:
                raise BusinessRuleError("L'installation initiale est déjà effectuée.")
            role = self._users.get_role_by_code("ADMIN")
            if role is None:
                raise BusinessRuleError("Le rôle Administrateur est introuvable.")
            user_id = self._users.insert(
                identifiant=identifiant,
                nom=nom,
                prenom=prenom,
                password_hash=hash_password(password),
                role_id=role.id,
                must_change_password=False,  # il vient de choisir son mot de passe
                created_by=None,
            )
            self._audit.add(
                user_id=user_id,
                action="FIRST_ADMIN_CREATED",
                entity_type="user",
                entity_id=user_id,
            )
            user = self._users.get_by_id(user_id)
        assert user is not None
        return user

    # --- connexion -------------------------------------------------------------
    def login(self, identifiant: str, password: str) -> UserContext:
        identifiant = identifiant.strip()
        error: AppError | None = None
        context: UserContext | None = None

        # Les échecs doivent être enregistrés (compteur, audit) : on ne lève
        # l'exception qu'après la fin de la transaction, pour ne pas l'annuler.
        with transaction(self._conn):
            user = self._users.get_by_identifiant(identifiant)
            now = self._clock()

            if user is None:
                hash_password("temps-constant")  # égalise le temps de réponse
                self._audit.add(
                    user_id=None,
                    action="LOGIN_FAILED",
                    details={"identifiant": identifiant[:64]},
                )
                error = AuthenticationError(GENERIC_LOGIN_ERROR)
            elif user.locked_until and from_iso(user.locked_until) > now:
                remaining = from_iso(user.locked_until) - now
                minutes = max(1, math.ceil(remaining.total_seconds() / 60))
                error = AccountLockedError(
                    f"Compte temporairement verrouillé. Réessayez dans {minutes} minute(s)."
                )
            elif not verify_password(password, user.password_hash):
                attempts = user.failed_attempts + 1
                locked_until: str | None = None
                if attempts >= MAX_FAILED_ATTEMPTS:
                    locked_until = to_iso(now + timedelta(minutes=LOCK_MINUTES))
                    attempts = 0
                self._users.register_failed_attempt(user.id, attempts, locked_until)
                self._audit.add(
                    user_id=user.id,
                    action="LOGIN_FAILED",
                    entity_type="user",
                    entity_id=user.id,
                    details={"verrouille": locked_until is not None},
                )
                error = AuthenticationError(GENERIC_LOGIN_ERROR)
            elif not user.is_active:
                self._audit.add(
                    user_id=user.id,
                    action="LOGIN_REFUSED",
                    entity_type="user",
                    entity_id=user.id,
                    details={"raison": "compte désactivé"},
                )
                error = AccountDisabledError(
                    "Ce compte est désactivé. Contactez un administrateur."
                )
            else:
                self._users.register_login(user.id, to_iso(now))
                self._audit.add(
                    user_id=user.id, action="LOGIN", entity_type="user", entity_id=user.id
                )
                permissions = self._users.get_permission_codes(user.role_id)
                context = UserContext.from_user(user, permissions)

        if error is not None:
            raise error
        assert context is not None
        return context

    # --- changement de mot de passe -------------------------------------------
    def change_password(
        self, ctx: UserContext, old_password: str, new_password: str
    ) -> UserContext:
        """Autorisé même si `must_change_password` est actif (c'est son but)."""
        validate_password_policy(new_password, ctx.identifiant)
        if new_password == old_password:
            raise BusinessRuleError("Le nouveau mot de passe doit être différent de l'ancien.")

        error: AppError | None = None
        new_context: UserContext | None = None
        with transaction(self._conn):
            user = self._users.get_by_id(ctx.user_id)
            if user is None or not user.is_active:
                error = AuthenticationError("Compte introuvable ou désactivé.")
            elif not verify_password(old_password, user.password_hash):
                self._audit.add(
                    user_id=user.id,
                    action="PASSWORD_CHANGE_FAILED",
                    entity_type="user",
                    entity_id=user.id,
                )
                error = AuthenticationError("L'ancien mot de passe est incorrect.")
            else:
                self._users.set_password(user.id, hash_password(new_password), False)
                self._audit.add(
                    user_id=user.id,
                    action="PASSWORD_CHANGED",
                    entity_type="user",
                    entity_id=user.id,
                )
                refreshed = self._users.get_by_id(user.id)
                assert refreshed is not None
                new_context = UserContext.from_user(
                    refreshed, self._users.get_permission_codes(refreshed.role_id)
                )

        if error is not None:
            raise error
        assert new_context is not None
        return new_context
