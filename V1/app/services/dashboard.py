"""Tableau de bord adapté au profil : administrateur, pharmacien, caissier."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from calendar import monthrange
from datetime import date, datetime

from app.core.security import Permission, UserContext
from app.core.utils import (
    format_fcfa,
    format_local,
    local_day_bounds,
    local_today,
    now_utc,
)
from app.models import LOT_ETATS, CashSession, format_quantity
from app.repositories import LotRepository, SettingsRepository,CashRepository, SaleRepository, StatsRepository
from app.services.lots import DEFAULT_ALERT_DAYS, lot_etat

TABLE_LIMIT = 12

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    alert: bool = False
    hint: str = ""


@dataclass(frozen=True)
class TableData:
    titre: str
    colonnes: list[str]
    lignes: list[list[str]]
    vide: str = "Rien à signaler."


@dataclass(frozen=True)
class Dashboard:
    profil: str
    kpis: list[Kpi]
    tables: list[TableData]
    session: CashSession | None = None
    actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinanceReport:
    """Situation financière d'un mois ou d'une année (administrateur)."""

    titre: str
    kpis: list[Kpi]
    tables: list[TableData]


def _variation(current: int, previous: int, label: str) -> str:
    """Évolution en % par rapport à la période précédente (texte pour une carte KPI)."""
    if previous <= 0:
        return f"pas de ventes en {label}" if current else ""
    pct = (current - previous) * 100 / previous
    return f"{pct:+.1f} % vs {label}".replace(".", ",")


class DashboardService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._clock = clock
        self._lots = LotRepository(conn)
        self._stats = StatsRepository(conn)
        self._sales = SaleRepository(conn)
        self._cash = CashRepository(conn)
        self._settings = SettingsRepository(conn)

    def build(self, ctx: UserContext) -> Dashboard:
        profil = self._profile(ctx)

        if profil == "admin":
            ctx.require(Permission.REPORTS_FINANCIAL)
            return self._admin(ctx)

        if profil == "pharmacien":
            ctx.require(Permission.STOCK_VIEW)
            return self._pharmacien(ctx)

        ctx.require(Permission.SALES_VIEW_OWN)
        return self._caissier(ctx)

    @staticmethod
    def _profile(ctx: UserContext) -> str:
        if (
            ctx.role_code == "ADMIN"
            or ctx.has(Permission.REPORTS_FINANCIAL)
        ):
            return "admin"

        if (
            ctx.role_code == "PHARMACIEN"
            or ctx.has(Permission.STOCK_VIEW)
        ):
            return "pharmacien"

        return "caissier"

    # --- Blocs partagés -------------------------------------------------

    def _today(self) -> tuple[str, str, str]:
        today = local_today(self._clock)
        start, end = local_day_bounds(today)
        return today.isoformat(), start, end

    def _stock_block(self) -> tuple[list[Kpi], list[TableData]]:
        today_iso, _, _ = self._today()

        alert_days = int(
            self._settings.get(
                "peremption_alerte_jours",
                str(DEFAULT_ALERT_DAYS),
            )
        )

        today = local_today(self._clock)

        lots = [
            (lot, lot_etat(lot, today, alert_days))
            for lot in self._lots.list()
        ]

        in_stock = [
            (lot, etat)
            for lot, etat in lots
            if lot.quantite_disponible > 0
        ]

        vendable = sum(
            1 for _, etat in in_stock
            if etat in ("OK", "PROCHE")
        )

        proches = [
            (lot, etat)
            for lot, etat in in_stock
            if etat == "PROCHE"
        ]

        perimes = [
            (lot, etat)
            for lot, etat in in_stock
            if etat == "EXPIRE"
        ]

        rupture: list[list[str]] = []
        sous_seuil: list[list[str]] = []

        for row in self._stats.product_stock(today_iso):
            qty = format_quantity(
                row["stock"],
                row["unite_vente"],
                row["sous_unite"],
                row["sous_unites_par_unite"],
            )

            seuil = format_quantity(
                row["seuil_minimal"],
                row["unite_vente"],
                row["sous_unite"],
                row["sous_unites_par_unite"],
            )

            if row["stock"] == 0:
                rupture.append([
                    row["code"],
                    row["nom_commercial"],
                    "Rupture",
                    seuil,
                ])

            elif (
                row["seuil_minimal"] > 0
                and row["stock"] <= row["seuil_minimal"]
            ):
                sous_seuil.append([
                    row["code"],
                    row["nom_commercial"],
                    qty,
                    seuil,
                ])

        kpis = [
            Kpi(
                "Produits actifs",
                str(self._stats.active_products()),
            ),
            Kpi("Lots disponibles", str(vendable)),
            Kpi(
                "Valeur du stock",
                format_fcfa(self._stats.stock_value()),
                hint="au coût d'achat",
            ),
            Kpi(
                "Produits en rupture",
                str(len(rupture)),
                alert=bool(rupture),
            ),
            Kpi(
                "Sous le seuil minimal",
                str(len(sous_seuil)),
                alert=bool(sous_seuil),
            ),
            Kpi(
                "Lots proches de la péremption",
                str(len(proches)),
                alert=bool(proches),
                hint=f"dans {alert_days} jours",
            ),
            Kpi(
                "Lots périmés en stock",
                str(len(perimes)),
                alert=bool(perimes),
            ),
        ]

        surveiller = sorted(
            proches + perimes,
            key=lambda item: item[0].date_peremption,
        )

        tables = [
            TableData(
                "Produits en rupture ou sous le seuil",
                [
                    "Code",
                    "Produit",
                    "Stock vendable",
                    "Seuil minimal",
                ],
                (rupture + sous_seuil)[:TABLE_LIMIT],
                "Aucun produit en rupture ni sous le seuil.",
            ),
            TableData(
                "Lots proches de la péremption ou périmés",
                [
                    "Produit",
                    "Lot",
                    "Péremption",
                    "Disponible",
                    "État",
                ],
                [
                    [
                        lot.product_nom,
                        lot.numero_lot,
                        (
                            f"{lot.date_peremption[8:10]}/"
                            f"{lot.date_peremption[5:7]}/"
                            f"{lot.date_peremption[:4]}"
                        ),
                        lot.format_quantity(lot.quantite_disponible),
                        LOT_ETATS[etat],
                    ]
                    for lot, etat in surveiller[:TABLE_LIMIT]
                ],
                "Aucun lot à surveiller.",
            ),
        ]

        return kpis, tables

    # --- Situation financière (mois / année) ----------------------------

    def _period_totals(self, first: date, last: date) -> tuple[int, int]:
        """(nombre de ventes, chiffre d'affaires) du jour `first` au jour `last` inclus."""
        start, _ = local_day_bounds(first)
        _, end = local_day_bounds(last)
        count, ca = self._stats.sales_totals(start, end)
        return int(count), int(ca)

    def finance(
        self,
        ctx: UserContext,
        mode: str = "month",
        year: int | None = None,
        month: int | None = None,
    ) -> FinanceReport:
        """Chiffres d'un mois (`mode="month"`) ou d'une année (`mode="year"`).

        Les ventes annulées sont exclues par `StatsRepository.sales_totals`, comme pour
        les indicateurs du jour.
        """
        ctx.require(Permission.REPORTS_FINANCIAL)
        today = local_today(self._clock)
        year = year or today.year
        month = month or today.month
        if mode not in ("month", "year") or not 1 <= month <= 12:
            raise ValueError("Période invalide.")
        if mode == "year":
            return self._finance_year(year)
        return self._finance_month(year, month)

    def _finance_month(self, year: int, month: int) -> FinanceReport:
        first = date(year, month, 1)
        days = monthrange(year, month)[1]
        last = date(year, month, days)
        count, ca = self._period_totals(first, last)

        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        prev_count, prev_ca = self._period_totals(
            date(prev_year, prev_month, 1),
            date(prev_year, prev_month, monthrange(prev_year, prev_month)[1]),
        )
        prev_label = MONTHS_FR[prev_month - 1].lower()
        cumul_count, cumul_ca = self._period_totals(date(year, 1, 1), last)
        nb_creances, creances = self._stats.receivables()

        kpis = [
            Kpi(
                "Chiffre d'affaires du mois",
                format_fcfa(ca),
                hint=_variation(ca, prev_ca, prev_label),
            ),
            Kpi(
                "Ventes du mois",
                str(count),
                hint=_variation(count, prev_count, prev_label),
            ),
            Kpi("Panier moyen", format_fcfa(ca // count if count else 0)),
            Kpi(
                f"Cumul {year}",
                format_fcfa(cumul_ca),
                hint=f"{cumul_count} vente(s) depuis le 1er janvier",
            ),
            Kpi(
                "Créances clients",
                format_fcfa(creances),
                alert=creances > 0,
                hint=f"{nb_creances} vente(s) à solder (total en cours)",
            ),
        ]

        lignes: list[list[str]] = []
        for day in range(1, days + 1):
            d = date(year, month, day)
            c, amount = self._period_totals(d, d)
            if c:
                lignes.append([d.strftime("%d/%m/%Y"), str(c), format_fcfa(amount)])
        if lignes:
            lignes.append(["Total", str(count), format_fcfa(ca)])

        table = TableData(
            f"Ventes par jour : {MONTHS_FR[month - 1]} {year}",
            ["Jour", "Ventes", "Chiffre d'affaires"],
            lignes,
            "Aucune vente sur ce mois.",
        )
        return FinanceReport(f"{MONTHS_FR[month - 1]} {year}", kpis, [table])

    def _finance_year(self, year: int) -> FinanceReport:
        months: list[tuple[int, int]] = []
        for month in range(1, 13):
            months.append(
                self._period_totals(
                    date(year, month, 1), date(year, month, monthrange(year, month)[1])
                )
            )
        count = sum(c for c, _ in months)
        ca = sum(a for _, a in months)
        prev_count, prev_ca = self._period_totals(date(year - 1, 1, 1), date(year - 1, 12, 31))
        nb_creances, creances = self._stats.receivables()

        best = max(range(12), key=lambda i: months[i][1])
        kpis = [
            Kpi(
                f"Chiffre d'affaires {year}",
                format_fcfa(ca),
                hint=_variation(ca, prev_ca, str(year - 1)),
            ),
            Kpi(
                f"Ventes {year}",
                str(count),
                hint=_variation(count, prev_count, str(year - 1)),
            ),
            Kpi("Panier moyen", format_fcfa(ca // count if count else 0)),
            Kpi(
                "Meilleur mois",
                MONTHS_FR[best] if months[best][1] else "-",
                hint=format_fcfa(months[best][1]) if months[best][1] else "aucune vente",
            ),
            Kpi(
                "Créances clients",
                format_fcfa(creances),
                alert=creances > 0,
                hint=f"{nb_creances} vente(s) à solder (total en cours)",
            ),
        ]

        lignes = [
            [
                MONTHS_FR[i],
                str(c),
                format_fcfa(a),
                f"{a * 100 / ca:.1f} %".replace(".", ",") if ca else "",
            ]
            for i, (c, a) in enumerate(months)
        ]
        if ca:
            lignes.append(["Total", str(count), format_fcfa(ca), "100 %"])

        table = TableData(
            f"Ventes par mois : {year}",
            ["Mois", "Ventes", "Chiffre d'affaires", "Part de l'année"],
            lignes if ca else [],
            f"Aucune vente en {year}.",
        )
        return FinanceReport(str(year), kpis, [table])

    # --- Profils --------------------------------------------------------

    def _admin(self, ctx: UserContext) -> Dashboard:
        _, start, end = self._today()

        count, ca = self._stats.sales_totals(start, end)
        nb_creances, creances = self._stats.receivables()

        stock_kpis, tables = self._stock_block()

        kpis = [
            Kpi("Ventes du jour", str(count)),
            Kpi("Chiffre d'affaires du jour", format_fcfa(ca)),
            Kpi(
                "Dépenses du jour",
                "—",
                hint="module Dépenses à venir",
            ),
            Kpi(
                "Créances clients",
                format_fcfa(creances),
                alert=creances > 0,
                hint=f"{nb_creances} vente(s) à solder",
            ),
            Kpi(
                "Dettes fournisseurs",
                "—",
                hint="module Approvisionnements à venir",
            ),
            *stock_kpis,
        ]

        return Dashboard(
            "admin",
            kpis,
            tables,
            actions=["sales"],
        )

    def _pharmacien(self, ctx: UserContext) -> Dashboard:
        _, start, end = self._today()

        count, _ca = self._stats.sales_totals(start, end)
        stock_kpis, tables = self._stock_block()

        kpis = [
            *stock_kpis,
            Kpi("Ventes du jour", str(count)),
        ]

        return Dashboard(
            "pharmacien",
            kpis,
            tables,
            actions=["cash", "sales"],
        )

    def _caissier(self, ctx: UserContext) -> Dashboard:
        _, start, end = self._today()

        count, ca = self._stats.sales_totals(
            start,
            end,
            ctx.user_id,
        )

        session = self._cash.get_open(ctx.user_id)

        kpis = [
            Kpi("Mes ventes du jour", str(count)),
            Kpi(
                "Mon chiffre d'affaires du jour",
                format_fcfa(ca),
            ),
            Kpi(
                "Ma caisse",
                "Ouverte" if session else "Fermée",
                alert=session is None,
                hint=(
                    f"depuis {format_local(session.ouverte_le)}"
                    if session
                    else "à ouvrir"
                ),
            ),
        ]

        recent = self._sales.list(
            start,
            end,
            ctx.user_id,
            limit=TABLE_LIMIT,
        )

        table = TableData(
            "Mes dernières ventes du jour",
            [
                "N° de vente",
                "Heure",
                "Net à payer",
                "Reste",
                "Statut",
            ],
            [
                [
                    s.numero_vente,
                    format_local(s.date_vente)[-5:],
                    format_fcfa(s.montant_net),
                    format_fcfa(s.reste) if s.reste else "",
                    "Annulée" if s.is_cancelled else "Validée",
                ]
                for s in recent
            ],
            "Aucune vente aujourd'hui.",
        )

        return Dashboard(
            "caissier",
            kpis,
            [table],
            session=session,
            actions=["cash", "sales"],
        )