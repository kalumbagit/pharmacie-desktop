"""Pages fournisseurs : liste et formulaire."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from app.core.errors import AppError
from app.core.security import Permission
from app.models import Supplier
from app.services.suppliers import SupplierInput
from app.ui.theme import (
    MUTED,
    CardPage,
    fill_row,
    fit_columns,
    make_button,
    make_label,
    make_table,
    selected_index,
)

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_COLUMNS = ["Nom / raison sociale", "Téléphone", "Adresse", "Statut"]
_STATUS_FILTERS = [("Actifs", "ACTIF"), ("Inactifs", "INACTIF"), ("Tous", None)]


class SuppliersPage(QWidget):
    def __init__(self, win: MainWindow) -> None:
        super().__init__()
        self.win = win
        self._suppliers: list[Supplier] = []
        can_edit = win.ctx.has(Permission.SUPPLIERS_EDIT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(make_label("Fournisseurs", "title"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (nom, téléphone, adresse)…")
        self.status_filter = QComboBox()
        for label, value in _STATUS_FILTERS:
            self.status_filter.addItem(label, value)
        self.btn_new = make_button("Nouveau fournisseur")
        self.btn_edit = make_button("Modifier", "secondary")
        self.btn_toggle = make_button("Désactiver", "secondary")
        self.btn_history = make_button("Historique", "secondary")
        self.btn_new.clicked.connect(lambda _checked=False: win.show_supplier_form(None))
        self.btn_edit.clicked.connect(lambda _checked=False: self._edit())
        self.btn_toggle.clicked.connect(lambda _checked=False: self._toggle())
        self.btn_history.clicked.connect(lambda _checked=False: self._show_history())
        self.search.textChanged.connect(lambda _text: self.reload())
        self.status_filter.currentIndexChanged.connect(lambda _index: self.reload())

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status_filter)
        if can_edit:
            bar.addWidget(self.btn_new)
            bar.addWidget(self.btn_edit)
            bar.addWidget(self.btn_toggle)
        if win.ctx.has(Permission.LOTS_VIEW):
            bar.addWidget(self.btn_history)
        layout.addLayout(bar)

        self.table = make_table(_COLUMNS)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        if can_edit:
            self.table.itemDoubleClicked.connect(lambda _item: self._edit())
        layout.addWidget(self.table, 1)
        self.reload()

    def reload(self) -> None:
        index = selected_index(self.table)
        selected_id = self._suppliers[index].id if index is not None else None
        try:
            self._suppliers = self.win.suppliers.list_suppliers(
                self.win.ctx, self.search.text(), self.status_filter.currentData()
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        self.table.setRowCount(len(self._suppliers))
        for row, s in enumerate(self._suppliers):
            fill_row(
                self.table,
                row,
                [
                    s.nom,
                    s.telephone or "",
                    s.adresse or "",
                    "Actif" if s.is_active else "Désactivé",
                ],
                foreground=None if s.is_active else MUTED,
            )
            if s.id == selected_id:
                self.table.selectRow(row)
        fit_columns(self.table, 2)
        self._update_buttons()

    def _selected(self) -> Supplier | None:
        index = selected_index(self.table)
        return self._suppliers[index] if index is not None else None

    def _update_buttons(self) -> None:
        supplier = self._selected()
        for button in (self.btn_edit, self.btn_toggle, self.btn_history):
            button.setEnabled(supplier is not None)
        inactive = supplier is not None and not supplier.is_active
        self.btn_toggle.setText("Réactiver" if inactive else "Désactiver")

    def _edit(self) -> None:
        supplier = self._selected()
        if supplier is not None:
            self.win.show_supplier_form(supplier)

    def _show_history(self) -> None:
        supplier = self._selected()
        if supplier is not None:
            self.win.show_supplier_history(supplier.id, supplier.nom)

    def _toggle(self) -> None:
        supplier = self._selected()
        if supplier is None:
            return
        activate = not supplier.is_active
        if not activate:
            answer = QMessageBox.question(
                self,
                "Désactiver le fournisseur",
                f"Désactiver « {supplier.nom} » ?\n"
                "Il ne pourra plus être choisi pour une réception.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.win.suppliers.set_active(self.win.ctx, supplier.id, activate)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        self.reload()


class SupplierFormPage(CardPage):
    def __init__(self, win: MainWindow, supplier: Supplier | None = None) -> None:
        super().__init__("Modifier le fournisseur" if supplier else "Nouveau fournisseur")
        self.win = win
        self._supplier = supplier
        self.nom = QLineEdit(supplier.nom if supplier else "")
        self.telephone = QLineEdit(supplier.telephone or "" if supplier else "")
        self.adresse = QLineEdit(supplier.adresse or "" if supplier else "")
        self.form.addRow("Nom / raison sociale *", self.nom)
        self.form.addRow("Téléphone", self.telephone)
        self.form.addRow("Adresse", self.adresse)

        save = make_button("Enregistrer")
        save.clicked.connect(lambda _checked=False: self._submit())
        self.adresse.returnPressed.connect(self._submit)
        cancel = make_button("Annuler", "secondary")
        cancel.clicked.connect(lambda _checked=False: win.show_suppliers())
        self.add_buttons(cancel, save)
        self.nom.setFocus()

    def _submit(self) -> None:
        data = SupplierInput(self.nom.text(), self.telephone.text(), self.adresse.text())
        try:
            if self._supplier is None:
                self.win.suppliers.create_supplier(self.win.ctx, data)
            else:
                self.win.suppliers.update_supplier(self.win.ctx, self._supplier.id, data)
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.show_suppliers()