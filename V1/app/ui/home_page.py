"""Tableau de bord : indicateurs et alertes adaptés au profil de l'utilisateur connecté."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.database import current_version
from app.core.errors import AppError
from app.services.dashboard import MONTHS_FR, Dashboard, FinanceReport, Kpi, TableData
from app.ui.theme import (
    fill_row,
    fit_columns,
    make_button,
    make_label,
    make_table,
)

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


KPI_COLUMNS = 4


class KpiCard(QFrame):
    def __init__(self, kpi: Kpi) -> None:
        super().__init__()

        self.setObjectName("kpi")
        self.setProperty("alert", "yes" if kpi.alert else "no")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        layout.addWidget(make_label(kpi.label, "kpiLabel"))

        value = make_label(kpi.value, "kpiValue")
        value.setProperty("alert", "yes" if kpi.alert else "no")
        layout.addWidget(value)

        if kpi.hint:
            layout.addWidget(make_label(kpi.hint, "kpiHint"))


def _clear_layout(layout) -> None:  # noqa: ANN001
    """Vide un layout (widgets et sous-layouts) avant de le reconstruire."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()  # disparaît tout de suite ; la suppression réelle vient après
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _table_panel(data: TableData, stretch_column: int | None = None) -> QFrame:
    panel = QFrame()
    panel.setObjectName("panel")

    layout = QVBoxLayout(panel)
    layout.setContentsMargins(16, 12, 16, 12)

    layout.addWidget(make_label(data.titre, "sectionTitle"))

    if not data.lignes:
        layout.addWidget(make_label(data.vide, "muted"))
        return panel

    if stretch_column is None:
        stretch_column = 1 if len(data.colonnes) > 1 else 0

    table = make_table(data.colonnes, stretch_column=stretch_column)

    table.setRowCount(len(data.lignes))

    for row, cells in enumerate(data.lignes):
        fill_row(table, row, cells)

    fit_columns(table)

    table.setMinimumHeight(
        min(34 * (len(data.lignes) + 1) + 6, 330)
    )

    layout.addWidget(table)

    return panel


class HomePage(QWidget):
    """Accueil. Pour l'administrateur : situation financière du mois ou de l'année."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__()

        self.win = win
        self.dashboard: Dashboard | None = None

        ctx = win.ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("pagescroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        layout.addWidget(
            make_label(
                f"Bonjour, {ctx.nom_complet}",
                "title",
            )
        )

        layout.addWidget(
            make_label(
                f"Tableau de bord : {ctx.role_label}",
                "muted",
            )
        )

        try:
            self.dashboard = win.dashboard.build(ctx)

        except AppError as exc:
            layout.addWidget(make_label(str(exc), "error"))
            layout.addStretch(1)
            return

        dash = self.dashboard

        # --- Actions rapides --------------------------------------------

        actions = QHBoxLayout()
        actions.setSpacing(10)

        if "cash" in dash.actions:
            label = (
                "Aller à la caisse"
                if dash.session
                else "Ouvrir la caisse"
            )

            self.btn_cash = make_button(label)

            self.btn_cash.clicked.connect(
                lambda _checked=False: win.show_cash()
            )

            actions.addWidget(self.btn_cash)

        if "sales" in dash.actions:
            self.btn_sales = make_button(
                "Consulter les ventes",
                "secondary",
            )

            self.btn_sales.clicked.connect(
                lambda _checked=False: win.show_sales()
            )

            actions.addWidget(self.btn_sales)

        actions.addStretch(1)
        layout.addLayout(actions)

        # --- Indicateurs KPI --------------------------------------------

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for index, kpi in enumerate(dash.kpis):
            grid.addWidget(
                KpiCard(kpi),
                index // KPI_COLUMNS,
                index % KPI_COLUMNS,
            )

        for column in range(KPI_COLUMNS):
            grid.setColumnStretch(column, 1)

        layout.addLayout(grid)

        # --- Situation financière (administrateur) ----------------------

        if dash.profil == "admin":
            layout.addWidget(self._build_finance_panel())

        # --- Tableaux d'informations ------------------------------------

        for data in dash.tables:
            layout.addWidget(_table_panel(data))

        layout.addStretch(1)

        # --- Informations sur la base de données ------------------------

        layout.addWidget(
            make_label(
                f"Base de données : {win.settings.db_path.name} "
                f"(migration {current_version(win.conn):04d})",
                "muted",
            )
        )

    # --- Situation financière ---------------------------------------------

    def _build_finance_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        today = date.today()

        self.fin_mode = QComboBox()
        self.fin_mode.addItem("Par mois", "month")
        self.fin_mode.addItem("Par année", "year")

        self.fin_month = QComboBox()
        for number, name in enumerate(MONTHS_FR, start=1):
            self.fin_month.addItem(name, number)
        self.fin_month.setCurrentIndex(today.month - 1)

        self.fin_year = QComboBox()
        for year in range(today.year, today.year - 8, -1):
            self.fin_year.addItem(str(year), year)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(make_label("Situation financière", "sectionTitle"), 1)
        head.addWidget(self.fin_mode)
        head.addWidget(self.fin_month)
        head.addWidget(self.fin_year)
        outer.addLayout(head)

        self.fin_body = QVBoxLayout()
        self.fin_body.setSpacing(10)
        outer.addLayout(self.fin_body)

        self.fin_mode.currentIndexChanged.connect(lambda _i: self._reload_finance())
        self.fin_month.currentIndexChanged.connect(lambda _i: self._reload_finance())
        self.fin_year.currentIndexChanged.connect(lambda _i: self._reload_finance())
        self._reload_finance()

        return panel

    def _reload_finance(self) -> None:
        mode = self.fin_mode.currentData()
        self.fin_month.setEnabled(mode == "month")

        _clear_layout(self.fin_body)

        try:
            report: FinanceReport = self.win.dashboard.finance(
                self.win.ctx,
                mode,
                self.fin_year.currentData(),
                self.fin_month.currentData(),
            )
        except (AppError, ValueError) as exc:
            self.fin_body.addWidget(make_label(str(exc), "error"))
            return

        self.fin_body.addWidget(make_label(report.titre, "muted"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for index, kpi in enumerate(report.kpis):
            grid.addWidget(KpiCard(kpi), index // KPI_COLUMNS, index % KPI_COLUMNS)

        for column in range(KPI_COLUMNS):
            grid.setColumnStretch(column, 1)

        self.fin_body.addLayout(grid)

        for data in report.tables:
            self.fin_body.addWidget(_table_panel(data, stretch_column=0))