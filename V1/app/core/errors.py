"""Exceptions métier : leur message est destiné à être affiché à l'utilisateur."""


class AppError(Exception):
    """Erreur de base de l'application."""


class ValidationError(AppError):
    """Donnée saisie invalide."""


class BusinessRuleError(AppError):
    """Règle métier violée."""


class AuthenticationError(AppError):
    """Échec d'authentification."""


class AccountDisabledError(AuthenticationError):
    """Le compte est désactivé."""


class AccountLockedError(AuthenticationError):
    """Le compte est temporairement verrouillé."""


class PermissionDeniedError(AppError):
    """L'utilisateur n'a pas la permission requise."""


class MustChangePasswordError(PermissionDeniedError):
    """Le mot de passe doit être changé avant toute autre action."""
