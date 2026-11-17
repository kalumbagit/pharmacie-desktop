
"""Sessions de caisse : ouverture avec fond de caisse, clôture avec contrôle d'écart."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.database import transaction
from app.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from app.core.security import Permission, UserContext
from app.core.utils import now_utc, to_iso
from app.models import CashSession
from app.repositories import AuditRepository,CashRepository

MAX_AMOUNT = 100_000_000


@dataclass(frozen=True)
class SessionSummary:
    session: CashSession
    nombre_ventes: int
    totaux: list[dict[str, Any]]
    especes_nettes: int
    montant_attendu: int


class CashService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._cash = CashRepository(conn)
        self._audit = AuditRepository(conn)

    def get_open_session(self, ctx: UserContext) -> CashSession | None:
        ctx.require(Permission.CASH_SESSION)
        return self._cash.get_open(ctx.user_id)

    def open_session(
        self,
        ctx: UserContext,
        fond_ouverture: int = 0,
    ) -> CashSession:
        ctx.require(Permission.CASH_SESSION)

        if (
            not isinstance(fond_ouverture, int)
            or not 0 <= fond_ouverture <= MAX_AMOUNT
        ):
            raise ValidationError("Fond de caisse invalide.")

        with transaction(self._conn):
            if self._cash.get_open(ctx.user_id) is not None:
                raise BusinessRuleError("Une session de caisse est déjà ouverte.")

            session_id = self._cash.insert(
                ctx.user_id,
                to_iso(self._clock()),
                fond_ouverture,
            )

            self._audit.add(
                user_id=ctx.user_id,
                action="CASH_OPENED",
                entity_type="cash_session",
                entity_id=session_id,
                details={"fond_ouverture": fond_ouverture},
            )

            session = self._cash.get(session_id)

        assert session is not None
        return session

    def summary(
        self,
        ctx: UserContext,
        session_id: int,
    ) -> SessionSummary:
        ctx.require(Permission.CASH_SESSION)

        session = self._require(session_id)

        if (
            session.user_id != ctx.user_id
            and not ctx.has(Permission.SALES_VIEW_ALL)
        ):
            raise PermissionDeniedError(
                "Cette session de caisse ne vous appartient pas."
            )

        return self._summary(session)

    def close_session(
        self,
        ctx: UserContext,
        session_id: int,
        montant_compte: int,
    ) -> CashSession:
        """Clôture : compare les espèces comptées aux espèces attendues et fige l'écart."""
        ctx.require(Permission.CASH_SESSION)

        if (
            not isinstance(montant_compte, int)
            or not 0 <= montant_compte <= MAX_AMOUNT
        ):
            raise ValidationError("Montant compté invalide.")

        with transaction(self._conn):
            session = self._require(session_id)

            if session.user_id != ctx.user_id:
                raise PermissionDeniedError(
                    "Vous ne pouvez clôturer que votre propre caisse."
                )

            if not session.is_open:
                raise BusinessRuleError("Cette session est déjà clôturée.")

            attendu = self._summary(session).montant_attendu
            ecart = montant_compte - attendu

            self._cash.close(
                session_id,
                to_iso(self._clock()),
                attendu,
                montant_compte,
                ecart,
            )

            self._audit.add(
                user_id=ctx.user_id,
                action="CASH_CLOSED",
                entity_type="cash_session",
                entity_id=session_id,
                details={
                    "attendu": attendu,
                    "compte": montant_compte,
                    "ecart": ecart,
                },
            )

            closed = self._cash.get(session_id)

        assert closed is not None
        return closed

    # --- interne -------------------------------------------------------------------

    def _summary(self, session: CashSession) -> SessionSummary:
        totaux = self._cash.totals_by_method(session.id)

        especes = sum(
            int(t["net"])
            for t in totaux
            if t["is_cash"]
        )

        return SessionSummary(
            session=session,
            nombre_ventes=self._cash.sales_count(session.id),
            totaux=totaux,
            especes_nettes=especes,
            montant_attendu=session.fond_ouverture + especes,
        )

    def _require(self, session_id: int) -> CashSession:
        session = self._cash.get(session_id)

        if session is None:
            raise BusinessRuleError("Session de caisse introuvable.")

        return session
