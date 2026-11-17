"""Sécurité : mots de passe, validations de saisie, permissions et contexte utilisateur."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from enum import StrEnum

import bcrypt

from app.core.errors import MustChangePasswordError, PermissionDeniedError, ValidationError
from app.models import User

# ----------------------------------------------------------------------------
# Mots de passe
# ----------------------------------------------------------------------------
BCRYPT_ROUNDS = 12
MIN_LENGTH = 6
MAX_BYTES = 72  # limite de bcrypt
POLICY_HINT = "6 caractères minimum, avec au moins une lettre et un chiffre."

_LOWER = "abcdefghjkmnpqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGITS = "23456789"


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def generate_temporary_password(length: int = 12) -> str:
    """Mot de passe aléatoire sans caractères ambigus (0/O, 1/l/I)."""
    pool = _LOWER + _UPPER + _DIGITS
    chars = [
        secrets.choice(_LOWER),
        secrets.choice(_UPPER),
        secrets.choice(_DIGITS),
        *(secrets.choice(pool) for _ in range(length - 3)),
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def validate_password_policy(password: str, identifiant: str | None = None) -> None:
    if len(password) < MIN_LENGTH:
        raise ValidationError(f"Le mot de passe est trop court. {POLICY_HINT}")
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("Le mot de passe est trop long (72 octets maximum).")
    if identifiant and password.lower() == identifiant.lower():
        raise ValidationError("Le mot de passe ne peut pas être identique à l'identifiant.")


# ----------------------------------------------------------------------------
# Validation des saisies utilisateur
# ----------------------------------------------------------------------------
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def validate_identifiant(identifiant: str) -> str:
    value = identifiant.strip()
    if not _IDENTIFIANT.match(value):
        raise ValidationError(
            "L'identifiant doit contenir de 3 à 32 caractères : "
            "lettres, chiffres, point, tiret ou underscore."
        )
    return value


def validate_name(value: str, label: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValidationError(f"Le champ « {label} » est obligatoire.")
    if len(cleaned) > 80:
        raise ValidationError(f"Le champ « {label} » est trop long.")
    return cleaned


# ----------------------------------------------------------------------------
# Permissions (doivent rester synchronisées avec la table `permissions`)
# ----------------------------------------------------------------------------
class Permission(StrEnum):
    USERS_MANAGE = "users.manage"
    SETTINGS_EDIT = "settings.edit"
    BACKUP_MANAGE = "backup.manage"
    AUDIT_VIEW = "audit.view"
    PRODUCTS_VIEW = "products.view"
    PRODUCTS_EDIT = "products.edit"
    PRICE_EDIT = "price.edit"
    LOTS_VIEW = "lots.view"
    SUPPLIERS_VIEW = "suppliers.view"
    SUPPLIERS_EDIT = "suppliers.edit"
    PURCHASES_VIEW = "purchases.view"
    PURCHASES_CREATE = "purchases.create"
    PURCHASES_PAY = "purchases.pay"
    STOCK_VIEW = "stock.view"
    STOCK_ADJUST = "stock.adjust"
    INVENTORY_RUN = "inventory.run"
    SALES_CREATE = "sales.create"
    SALES_VIEW_OWN = "sales.view_own"
    SALES_VIEW_ALL = "sales.view_all"
    SALES_DISCOUNT = "sales.discount"
    SALES_CANCEL = "sales.cancel"
    PAYMENTS_RECORD = "payments.record"
    CASH_SESSION = "cash.session"
    INVOICES_GENERATE = "invoices.generate"
    RETURNS_CREATE = "returns.create"
    EXPENSES_EDIT = "expenses.edit"
    ACCOUNTING_VIEW = "accounting.view"
    REPORTS_FINANCIAL = "reports.financial"
    REPORTS_STOCK = "reports.stock"


ROLE_LABELS = {
    "ADMIN": "Administrateur",
    "PHARMACIEN": "Pharmacien",
    "CAISSIER": "Caissier",
}


# ----------------------------------------------------------------------------
# Contexte de l'utilisateur connecté (transmis à chaque service)
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class UserContext:
    user_id: int
    identifiant: str
    nom_complet: str
    role_code: str
    permissions: frozenset[str]
    must_change_password: bool = False

    @classmethod
    def from_user(cls, user: User, permissions: frozenset[str]) -> UserContext:
        return cls(
            user_id=user.id,
            identifiant=user.identifiant,
            nom_complet=user.nom_complet,
            role_code=user.role_code,
            permissions=permissions,
            must_change_password=user.must_change_password,
        )

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role_code, self.role_code)

    def has(self, permission: Permission | str) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission | str) -> None:
        """Contrôle d'autorisation côté logique métier (pas seulement dans l'interface)."""
        if self.must_change_password:
            raise MustChangePasswordError("Vous devez d'abord définir votre nouveau mot de passe.")
        if permission not in self.permissions:
            raise PermissionDeniedError("Vous n'avez pas l'autorisation d'effectuer cette action.")
