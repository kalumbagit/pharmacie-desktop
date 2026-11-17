"""Fiche d'inventaire général : stock initial, entrées, sorties et stock théorique par lot.

Tout est calculé à partir du journal `stock_movements` (source de vérité) :

    stock initial   = somme des mouvements AVANT le début de la période
    entrées         = mouvements positifs de la période
    sorties         = mouvements négatifs de la période (en valeur absolue)
    stock théorique = stock initial + entrées - sorties

Les quantités sont exprimées dans l'unité de base du produit (la sous-unité si elle
existe, sinon l'unité de vente), comme partout dans l'application.
Lecture seule : ce service n'écrit jamais en base.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from app.core.errors import ValidationError
from app.core.security import Permission, UserContext
from app.core.utils import to_iso
from app.repositories import SettingsRepository

DEFAULT_ORGANISATION = "MEDICAL CENTER NEMI"


@dataclass(frozen=True)
class InventoryRow:
    lot_id: int
    code: str
    designation: str  # « Nom dosage - lot XXX » (une ligne par lot)
    categorie: str
    unite: str
    stock_initial: int
    entrees: int
    sorties: int
    date_peremption: str  # AAAA-MM-JJ

    @property
    def stock_theorique(self) -> int:
        return self.stock_initial + self.entrees - self.sorties


@dataclass(frozen=True)
class InventorySheet:
    organisation: str
    service: str
    categorie: str  # libellé du filtre (« Toutes » si aucun)
    date_debut: date
    date_fin: date
    responsable: str
    rows: list[InventoryRow] = field(default_factory=list)


def _utc_bound(day: date) -> str:
    """Minuit local du jour `day`, en horodatage ISO UTC (comme `created_at`)."""
    return to_iso(datetime.combine(day, time.min).astimezone(UTC))


class InventoryService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._settings = SettingsRepository(conn)

    def categories(self, ctx: UserContext) -> list[str]:
        ctx.require(Permission.REPORTS_STOCK)
        rows = self._conn.execute("SELECT nom FROM categories ORDER BY nom").fetchall()
        return [r["nom"] for r in rows]

    def build_sheet(
        self,
        ctx: UserContext,
        date_debut: date,
        date_fin: date,
        categorie: str | None = None,
        search: str = "",
        service: str = "Pharmacie",
    ) -> InventorySheet:
        ctx.require(Permission.REPORTS_STOCK)
        if date_fin < date_debut:
            raise ValidationError("La date de fin précède la date de début.")

        debut = _utc_bound(date_debut)
        fin = _utc_bound(date_fin + timedelta(days=1))  # la date de fin est incluse
        clauses = ["1 = 1"]
        # Ordre = celui des « ? » de la requête : initial, entrées (2), sorties (2), jointure.
        params: list[object] = [debut, debut, fin, debut, fin, fin]
        if categorie:
            clauses.append("c.nom = ?")
            params.append(categorie)
        if search.strip():
            like = "%" + search.strip().replace("%", "").replace("_", "") + "%"
            clauses.append("(p.nom_commercial LIKE ? OR p.code LIKE ? OR l.numero_lot LIKE ?)")
            params.extend([like] * 3)

        rows = self._conn.execute(
            "SELECT l.id AS lot_id, p.code, p.nom_commercial, p.dosage, l.numero_lot, "
            "l.date_peremption, COALESCE(c.nom, '') AS categorie, "
            "COALESCE(p.sous_unite, p.unite_vente) AS unite, "
            "COALESCE(SUM(CASE WHEN m.created_at < ? THEN m.quantite_signee END), 0) "
            "  AS initial, "
            "COALESCE(SUM(CASE WHEN m.created_at >= ? AND m.created_at < ? "
            "  AND m.quantite_signee > 0 THEN m.quantite_signee END), 0) AS entrees, "
            "COALESCE(SUM(CASE WHEN m.created_at >= ? AND m.created_at < ? "
            "  AND m.quantite_signee < 0 THEN -m.quantite_signee END), 0) AS sorties "
            "FROM lots l JOIN products p ON p.id = l.product_id "
            "LEFT JOIN categories c ON c.id = p.categorie_id "
            "LEFT JOIN stock_movements m ON m.lot_id = l.id AND m.created_at < ? "
            f"WHERE {' AND '.join(clauses)} "
            "GROUP BY l.id "
            "HAVING initial != 0 OR entrees != 0 OR sorties != 0 "
            "ORDER BY p.nom_commercial COLLATE NOCASE, l.date_peremption",
            params,
        ).fetchall()

        items = [
            InventoryRow(
                lot_id=r["lot_id"],
                code=r["code"],
                designation=(
                    f"{r['nom_commercial']}{' ' + r['dosage'] if r['dosage'] else ''}"
                    f" - lot {r['numero_lot']}"
                ),
                categorie=r["categorie"],
                unite=r["unite"],
                stock_initial=int(r["initial"]),
                entrees=int(r["entrees"]),
                sorties=int(r["sorties"]),
                date_peremption=r["date_peremption"],
            )
            for r in rows
        ]
        return InventorySheet(
            organisation=self._settings.get("nom_pharmacie", DEFAULT_ORGANISATION)
            or DEFAULT_ORGANISATION,
            service=service,
            categorie=categorie or "Toutes",
            date_debut=date_debut,
            date_fin=date_fin,
            responsable=ctx.nom_complet,
            rows=items,
        )