"""Page « Inventaire » : fiche d'inventaire général à l'écran et export PDF.

La colonne « Stock physique » (comptage) et « Observations » se saisissent directement
dans le tableau ; l'écart se recalcule. Ces saisies servent à l'export PDF. Elles ne sont
pas enregistrées en base : la clôture d'un inventaire (écarts -> mouvements de stock)
est une étape distincte.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.core.inventory_pdf import HEADERS, export_inventory_pdf
from app.core.utils import format_date
from app.services.inventory import InventoryRow, InventorySheet
from app.ui.theme import (
    ROSE_DARK,
    fill_row,
    fit_columns,
    make_button,
    make_date_edit,
    make_label,
    make_table,
)

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_COL_PHYSIQUE = 8
_COL_ECART = 9
_COL_OBS = 11
_EDITABLE = (_COL_PHYSIQUE, _COL_OBS)
_LOGO_FILENAME = "logo.png"


class InventoryPage(QWidget):
    def __init__(self, win: MainWindow) -> None:
        super().__init__()
        self.win = win
        self._sheet: InventorySheet | None = None
        self._physiques: dict[int, int | None] = {}
        self._observations: dict[int, str] = {}
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(make_label("Inventaire général", "title"))
        layout.addWidget(
            make_label(
                "Stock théorique = stock initial + entrées - sorties, calculé sur la période. "
                "Double-cliquez sur « Stock physique » pour saisir le comptage.",
                "muted",
            )
        )

        today = date.today()
        self.date_debut = make_date_edit()
        self.date_debut.setDate(self.date_debut.date().addDays(1 - today.day))  # 1er du mois
        self.date_fin = make_date_edit()
        self.category = QComboBox()
        self.category.addItem("Toutes les catégories", None)
        try:
            for name in win.inventory.categories(win.ctx):
                self.category.addItem(name, name)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (produit, code, n° de lot)…")
        self.blank = QCheckBox("Fiche vierge (comptage à la main)")
        self.btn_export = make_button("Exporter en PDF")

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(make_label("Du", "muted"))
        bar.addWidget(self.date_debut)
        bar.addWidget(make_label("au", "muted"))
        bar.addWidget(self.date_fin)
        bar.addWidget(self.category)
        bar.addWidget(self.search, 1)
        layout.addLayout(bar)

        actions = QHBoxLayout()
        actions.addWidget(self.blank)
        actions.addStretch(1)
        actions.addWidget(self.btn_export)
        layout.addLayout(actions)

        self.table = make_table(HEADERS)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)
        self.status = make_label("", "muted")
        layout.addWidget(self.status)

        self.date_debut.dateChanged.connect(lambda _d: self.reload())
        self.date_fin.dateChanged.connect(lambda _d: self.reload())
        self.category.currentIndexChanged.connect(lambda _i: self.reload())
        self.search.textChanged.connect(lambda _t: self.reload())
        self.btn_export.clicked.connect(lambda _checked=False: self._export())
        self.reload()

    # --- données -------------------------------------------------------------------
    def reload(self) -> None:
        try:
            self._sheet = self.win.inventory.build_sheet(
                self.win.ctx,
                self.date_debut.date().toPython(),
                self.date_fin.date().toPython(),
                self.category.currentData(),
                self.search.text(),
            )
        except AppError as exc:
            self._sheet = None
            self.table.setRowCount(0)
            self.status.setText(str(exc))
            self.btn_export.setEnabled(False)
            return

        rows = self._sheet.rows
        self._loading = True
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            fill_row(
                self.table, index,
                [
                    str(index + 1), row.code, row.designation, row.unite,
                    str(row.stock_initial), str(row.entrees), str(row.sorties),
                    str(row.stock_theorique), "", "", format_date(row.date_peremption), "",
                ],
                right=(4, 5, 6, 7, 8, 9),
            )
            for column in range(len(HEADERS)):
                item = self.table.item(index, column)
                if item is None:
                    continue
                if column in _EDITABLE:
                    continue
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            physique = self._physiques.get(row.lot_id)
            self.table.item(index, _COL_PHYSIQUE).setText("" if physique is None else str(physique))
            self.table.item(index, _COL_OBS).setText(self._observations.get(row.lot_id, ""))
            self._update_ecart(index, row)
        fit_columns(self.table, 2)
        self._loading = False
        self.btn_export.setEnabled(True)
        self._update_status()

    def _update_ecart(self, index: int, row: InventoryRow) -> None:
        physique = self._physiques.get(row.lot_id)
        item = self.table.item(index, _COL_ECART)
        if item is None:
            return
        if physique is None:
            item.setText("")
            return
        ecart = physique - row.stock_theorique
        item.setText(f"{ecart:+d}" if ecart else "0")
        color = QColor(ROSE_DARK) if ecart < 0 else QColor("black")
        item.setForeground(QBrush(color))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self._sheet is None:
            return
        row = self._sheet.rows[item.row()]
        if item.column() == _COL_OBS:
            self._observations[row.lot_id] = item.text().strip()
            return
        if item.column() != _COL_PHYSIQUE:
            return
        text = item.text().strip()
        if not text:
            self._physiques[row.lot_id] = None
        elif text.isdigit():
            self._physiques[row.lot_id] = int(text)
        else:
            self._loading = True
            previous = self._physiques.get(row.lot_id)
            item.setText("" if previous is None else str(previous))
            self._loading = False
            QMessageBox.warning(self, "Saisie invalide", "Saisissez un nombre entier positif.")
            return
        self._loading = True
        self._update_ecart(item.row(), row)
        self._loading = False
        self._update_status()

    def _update_status(self) -> None:
        if self._sheet is None:
            return
        counted = [r for r in self._sheet.rows if self._physiques.get(r.lot_id) is not None]
        gaps = [
            r for r in counted
            if self._physiques[r.lot_id] != r.stock_theorique  # type: ignore[index]
        ]
        self.status.setText(
            f"{len(self._sheet.rows)} ligne(s) (une par lot) - {len(counted)} comptée(s) - "
            f"{len(gaps)} écart(s) constaté(s)"
        )

    # --- export --------------------------------------------------------------------
    def _logo_path(self) -> Path | None:
        """Logo du filigrane : `<dossier des documents>/logo.png`, s'il est configuré.

        Facultatif : sans dossier configuré, la fiche est simplement produite sans filigrane
        (un logo absent ou illisible est de toute façon ignoré par le générateur de PDF)."""
        documents_dir = getattr(self.win.settings, "documents_dir", None)
        return Path(documents_dir) / _LOGO_FILENAME if documents_dir else None

    def _export(self) -> None:
        if self._sheet is None:
            return
        documents = Path.home() / "Documents"
        folder = documents if documents.is_dir() else Path.home()
        default = folder / f"inventaire_{self._sheet.date_fin:%Y-%m-%d}.pdf"
        filename, _filter = QFileDialog.getSaveFileName(
            self, "Exporter la fiche d'inventaire", str(default), "Fichier PDF (*.pdf)"
        )
        if not filename:
            return
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        try:
            path = export_inventory_pdf(
                self._sheet,
                filename,
                physiques=self._physiques,
                observations=self._observations,
                blank_count=self.blank.isChecked(),
                logo_path=self._logo_path(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export impossible", f"Le PDF n'a pas pu être créé :\n{exc}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.information(self, "Export terminé", f"PDF enregistré ici :\n{path}")