"""Pages lots : liste, réception de stock, historique fournisseur."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.core.security import Permission
from app.core.utils import format_date, format_local, iso_date
from app.models import (
    LOT_ETATS,
    MOVEMENT_LABELS,
    Lot,
    Product,
    Supplier,
    SupplierMovement,
)
from app.ui.theme import (
    MUTED,
    ROSE_DARK,
    ROSE_LIGHT,
    CardPage,
    fill_row,
    make_button,
    make_date_edit,
    make_label,
    make_spin,
    make_table,
    selected_index,
)

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_COLUMNS = [
    "Produit", "N° de lot", "Fournisseur", "Péremption", "Réception",
    "Reçu", "Disponible", "État",
]
_ETAT_FILTERS = [
    ("Tous les états", None),
    ("Vendables", "VENDABLE"),
    ("Péremption proche", "PROCHE"),
    ("Périmés", "EXPIRE"),
    ("Bloqués", "BLOQUE"),
    ("Épuisés", "EPUISE"),
]


class LotsPage(QWidget):
    def __init__(
        self,
        win: MainWindow,
        supplier_id: int | None = None,
        supplier_nom: str | None = None,
    ) -> None:
        super().__init__()
        self.win = win
        self._supplier_id = supplier_id
        self._lots: list[Lot] = []
        can_adjust = win.ctx.has(Permission.STOCK_ADJUST)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = "Lots et péremptions" + (f" : {supplier_nom}" if supplier_nom else "")
        layout.addWidget(make_label(title, "title"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (produit, code, n° de lot)…")
        self.etat_filter = QComboBox()
        for label, value in _ETAT_FILTERS:
            self.etat_filter.addItem(label, value)
        self.btn_receive = make_button("Réceptionner un lot")
        self.btn_add_to_lot = make_button("Ajouter au lot", "secondary")
        self.btn_edit = make_button("Modifier", "secondary")
        self.btn_block = make_button("Bloquer", "secondary")
        self.btn_all = make_button("Tous les lots", "secondary")
        self.btn_receive.clicked.connect(lambda _checked=False: win.show_lot_receive())
        self.btn_add_to_lot.clicked.connect(lambda _checked=False: self._add_to_selected())
        self.btn_edit.clicked.connect(lambda _checked=False: self._edit_selected())
        self.btn_block.clicked.connect(lambda _checked=False: self._toggle_block())
        self.btn_all.clicked.connect(lambda _checked=False: win.show_lots())
        self.search.textChanged.connect(lambda _text: self.reload())
        self.etat_filter.currentIndexChanged.connect(lambda _index: self.reload())

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.etat_filter)
        if can_adjust:
            bar.addWidget(self.btn_receive)
            bar.addWidget(self.btn_add_to_lot)
            bar.addWidget(self.btn_edit)
            bar.addWidget(self.btn_block)
        if supplier_id is not None:
            bar.addWidget(self.btn_all)
        layout.addLayout(bar)

        self.table = make_table(_COLUMNS)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        if can_adjust:
            # Double-clic : ajouter une livraison au lot (formulaire prérempli).
            self.table.itemDoubleClicked.connect(lambda _item: self._add_to_selected())
        layout.addWidget(self.table, 1)
        self.count_label = make_label("", "muted")
        layout.addWidget(self.count_label)

        self.reload()

    def reload(self) -> None:
        index = selected_index(self.table)
        selected_id = self._lots[index].id if index is not None else None
        try:
            self._lots = self.win.lots.list_lots(
                self.win.ctx,
                search=self.search.text(),
                etat=self.etat_filter.currentData(),
                supplier_id=self._supplier_id,
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        self.table.setRowCount(len(self._lots))
        for row, lot in enumerate(self._lots):
            cells = [
                f"{lot.product_code} : {lot.product_nom}",
                lot.numero_lot,
                lot.supplier_nom,
                format_date(lot.date_peremption),
                format_date(lot.date_reception),
                lot.format_quantity(lot.quantite_recue),
                lot.format_quantity(lot.quantite_disponible),
                LOT_ETATS.get(lot.etat, lot.etat),
            ]
            foreground = background = None
            if lot.etat == "EXPIRE":
                foreground, background = ROSE_DARK, ROSE_LIGHT
            elif lot.etat == "PROCHE":
                foreground = ROSE_DARK
            elif lot.etat in ("BLOQUE", "EPUISE"):
                foreground = MUTED
            fill_row(
                self.table, row, cells,
                foreground=foreground, background=background, right=(5, 6),
            )
            if lot.id == selected_id:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.count_label.setText(f"{len(self._lots)} lot(s)")
        self._update_buttons()

    def _selected(self) -> Lot | None:
        index = selected_index(self.table)
        return self._lots[index] if index is not None else None

    def _update_buttons(self) -> None:
        lot = self._selected()
        self.btn_add_to_lot.setEnabled(lot is not None and lot.etat not in ("EXPIRE", "BLOQUE"))
        self.btn_edit.setEnabled(lot is not None)
        self.btn_block.setEnabled(lot is not None)
        self.btn_block.setText("Débloquer" if lot is not None and lot.statut == "BLOQUE" else "Bloquer")

    def _add_to_selected(self) -> None:
        lot = self._selected()
        if lot is None:
            return
        if lot.etat == "EXPIRE":
            QMessageBox.information(
                self, "Ajout impossible", "Ce lot est périmé : il ne peut plus être alimenté."
            )
            return
        if lot.etat == "BLOQUE":
            QMessageBox.information(
                self, "Ajout impossible", "Ce lot est bloqué : débloquez-le avant d'y ajouter du stock."
            )
            return
        self.win.show_lot_add(lot)

    def _edit_selected(self) -> None:
        lot = self._selected()
        if lot is not None:
            self.win.show_lot_edit(lot)

    def _toggle_block(self) -> None:
        lot = self._selected()
        if lot is None:
            return
        blocked = lot.statut != "BLOQUE"
        motif = ""
        if blocked:
            motif, ok = QInputDialog.getText(
                self, "Bloquer le lot",
                f"Motif du blocage du lot « {lot.numero_lot} » :",
            )
            if not ok:
                return
        try:
            self.win.lots.set_blocked(self.win.ctx, lot.id, blocked, motif)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        self.reload()


class LotReceivePage(CardPage):
    """Réception d'un lot (stock initial). Le stock est compté dans la plus petite unité."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__(
            "Réceptionner un lot",
            "Crée le lot et enregistre automatiquement le mouvement de stock correspondant.",
            width=620,
        )
        self.win = win
        self._products: list[Product] = []
        suppliers: list[Supplier] = []
        try:
            self._products = win.products.list_products(win.ctx, statut="ACTIF")
            suppliers = win.suppliers.list_suppliers(win.ctx, statut="ACTIF")
        except AppError as exc:
            self.set_error(str(exc))

        self.product = QComboBox()
        self.product.setEditable(True)
        self.product.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for p in self._products:
            label = f"{p.code} : {p.nom_commercial}" + (f" {p.dosage}" if p.dosage else "")
            self.product.addItem(label, p.id)
        completer = self.product.completer()
        if completer is not None:
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.product.setCurrentIndex(-1)

        self.supplier = QComboBox()
        for s in suppliers:
            self.supplier.addItem(s.nom, s.id)
        self.supplier.setCurrentIndex(-1)

        self.numero = QLineEdit()
        self.fab_known = QCheckBox("Date de fabrication connue")
        self.fab_date = make_date_edit()
        self.fab_date.setEnabled(False)
        self.fab_known.toggled.connect(self.fab_date.setEnabled)
        self.peremption = make_date_edit(today=False)
        self.reception = make_date_edit()
        self.cond = QComboBox()
        self.quantite = make_spin(10_000_000, minimum=1)
        self.hint = make_label("", "muted")
        self.prix_achat = make_spin(suffix=" FCFA")

        self.form.addRow("Produit *", self.product)
        self.form.addRow("Fournisseur *", self.supplier)
        self.form.addRow("N° de lot *", self.numero)
        self.form.addRow("", self.fab_known)
        self.form.addRow("Fabrication", self.fab_date)
        self.form.addRow("Péremption *", self.peremption)
        self.form.addRow("Réception *", self.reception)
        self.form.addRow("Conditionnement", self.cond)
        self.form.addRow("Quantité reçue *", self.quantite)
        self.form.addRow("", self.hint)
        self.form.addRow("Prix d'achat total", self.prix_achat)

        self.product.currentTextChanged.connect(lambda _text: self._refresh_packaging())
        self._refresh_packaging()

        save = make_button("Enregistrer la réception")
        save.clicked.connect(lambda _checked=False: self._submit())
        cancel = make_button("Annuler", "secondary")
        cancel.clicked.connect(lambda _checked=False: win.show_lots())
        self.add_buttons(cancel, save)

    def _current_product(self) -> Product | None:
        index = self.product.findText(self.product.currentText())
        return self._products[index] if index >= 0 else None

    def _refresh_packaging(self) -> None:
        product = self._current_product()
        self.cond.clear()
        if product is None:
            self.hint.setText("Choisissez un produit de la liste.")
            return
        self.cond.addItem(product.unite_vente, "UNITE")
        if product.has_sous_unite:
            self.cond.addItem(product.sous_unite, "SOUS_UNITE")
            self.hint.setText(
                f"1 {product.unite_vente} = {product.sous_unites_par_unite} {product.sous_unite}. "
                f"Le stock est compté en {product.sous_unite}."
            )
        else:
            self.hint.setText(f"Le stock est compté en {product.unite_vente}.")

    def _submit(self) -> None:
        product = self._current_product()
        if product is None:
            self.set_error("Sélectionnez un produit dans la liste.")
            return
        if self.supplier.currentIndex() < 0:
            self.set_error("Sélectionnez un fournisseur.")
            return
        try:
            self.win.lots.receive_stock(
                self.win.ctx,
                product_id=product.id,
                supplier_id=self.supplier.currentData(),
                numero_lot=self.numero.text(),
                date_peremption=iso_date(self.peremption),
                date_reception=iso_date(self.reception),
                date_fabrication=iso_date(self.fab_date) if self.fab_known.isChecked() else "",
                quantite=self.quantite.value(),
                conditionnement=self.cond.currentData() or "UNITE",
                prix_achat_total=self.prix_achat.value(),
            )
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.show_lots()


def _set_date(edit, iso: str | None) -> None:
    """Place une date ISO (AAAA-MM-JJ) dans un QDateEdit."""
    if iso:
        edit.setDate(QDate.fromString(iso, "yyyy-MM-dd"))


class LotAddPage(CardPage):
    """Livraison complémentaire d'un lot existant.

    Produit, fournisseur, numéro et dates sont ceux du lot (lecture seule) : seuls la
    quantité, le conditionnement et le coût de CETTE livraison sont saisis."""

    def __init__(self, win: MainWindow, lot: Lot) -> None:
        super().__init__(
            "Ajouter au lot",
            f"Lot « {lot.numero_lot} » : saisissez uniquement la quantité et le coût de cette livraison.",
            width=620,
        )
        self.win = win
        self._lot = lot

        self.form.addRow("Produit", make_label(f"{lot.product_code} : {lot.product_nom}"))
        self.form.addRow("Fournisseur", make_label(lot.supplier_nom))
        self.form.addRow("N° de lot", make_label(lot.numero_lot))
        self.form.addRow(
            "Fabrication", make_label(format_date(lot.date_fabrication) if lot.date_fabrication else "—")
        )
        self.form.addRow("Péremption", make_label(format_date(lot.date_peremption)))
        self.form.addRow("Stock actuel", make_label(lot.format_quantity(lot.quantite_disponible)))

        self.cond = QComboBox()
        self.cond.addItem(lot.product_unite_vente, "UNITE")
        hint = f"Le stock est compté en {lot.product_unite_vente}."
        if lot.product_sous_unite:
            self.cond.addItem(lot.product_sous_unite, "SOUS_UNITE")
            hint = (
                f"1 {lot.product_unite_vente} = {lot.product_par_unite} {lot.product_sous_unite}. "
                f"Le stock est compté en {lot.product_sous_unite}."
            )
        self.quantite = make_spin(10_000_000, minimum=1)
        self.prix_achat = make_spin(suffix=" FCFA")

        self.form.addRow("Conditionnement", self.cond)
        self.form.addRow("Quantité livrée *", self.quantite)
        self.form.addRow("", make_label(hint, "muted"))
        self.form.addRow("Coût de cette livraison", self.prix_achat)

        save = make_button("Enregistrer la livraison")
        save.clicked.connect(lambda _checked=False: self._submit())
        cancel = make_button("Annuler", "secondary")
        cancel.clicked.connect(lambda _checked=False: win.show_lots())
        self.add_buttons(cancel, save)
        self.quantite.setFocus()

    def _submit(self) -> None:
        try:
            self.win.lots.add_to_lot(
                self.win.ctx,
                self._lot.id,
                quantite=self.quantite.value(),
                conditionnement=self.cond.currentData() or "UNITE",
                prix_achat_total=self.prix_achat.value(),
            )
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.show_lots()


class LotEditPage(CardPage):
    """Correction des informations d'un lot (erreur de saisie).

    Le produit et la quantité ne se modifient pas ici : la quantité ne varie que par
    mouvement de stock (ajout au lot, ajustement, inventaire)."""

    def __init__(self, win: MainWindow, lot: Lot) -> None:
        super().__init__(
            "Modifier le lot",
            "Corrige les informations du lot. Le produit et la quantité ne sont pas modifiables.",
            width=620,
        )
        self.win = win
        self._lot = lot
        suppliers: list[Supplier] = []
        try:
            suppliers = win.suppliers.list_suppliers(win.ctx, statut="ACTIF")
        except AppError as exc:
            self.set_error(str(exc))

        self.supplier = QComboBox()
        for s in suppliers:
            self.supplier.addItem(s.nom, s.id)
        if self.supplier.findData(lot.supplier_id) < 0:  # fournisseur désactivé depuis
            self.supplier.addItem(lot.supplier_nom, lot.supplier_id)
        self.supplier.setCurrentIndex(self.supplier.findData(lot.supplier_id))

        self.numero = QLineEdit(lot.numero_lot)
        self.fab_known = QCheckBox("Date de fabrication connue")
        self.fab_date = make_date_edit()
        self.fab_date.setEnabled(bool(lot.date_fabrication))
        self.fab_known.setChecked(bool(lot.date_fabrication))
        self.fab_known.toggled.connect(self.fab_date.setEnabled)
        _set_date(self.fab_date, lot.date_fabrication)
        self.peremption = make_date_edit(today=False)
        _set_date(self.peremption, lot.date_peremption)
        self.reception = make_date_edit()
        _set_date(self.reception, lot.date_reception)
        self.prix_achat = make_spin(suffix=" FCFA")
        self.prix_achat.setValue(lot.prix_achat_total)
        self.motif = QLineEdit()
        self.motif.setPlaceholderText("Obligatoire si le lot a déjà été vendu ou mouvementé")

        self.form.addRow("Produit", make_label(f"{lot.product_code} : {lot.product_nom}"))
        self.form.addRow("Quantité en stock", make_label(lot.format_quantity(lot.quantite_disponible)))
        self.form.addRow("Fournisseur *", self.supplier)
        self.form.addRow("N° de lot *", self.numero)
        self.form.addRow("", self.fab_known)
        self.form.addRow("Fabrication", self.fab_date)
        self.form.addRow("Péremption *", self.peremption)
        self.form.addRow("Réception *", self.reception)
        self.form.addRow("Prix d'achat total du lot", self.prix_achat)
        self.form.addRow("Motif", self.motif)

        save = make_button("Enregistrer les modifications")
        save.clicked.connect(lambda _checked=False: self._submit())
        cancel = make_button("Annuler", "secondary")
        cancel.clicked.connect(lambda _checked=False: win.show_lots())
        self.add_buttons(cancel, save)

    def _submit(self) -> None:
        try:
            self.win.lots.update_lot(
                self.win.ctx,
                self._lot.id,
                numero_lot=self.numero.text(),
                supplier_id=self.supplier.currentData(),
                date_peremption=iso_date(self.peremption),
                date_reception=iso_date(self.reception),
                date_fabrication=iso_date(self.fab_date) if self.fab_known.isChecked() else "",
                prix_achat_total=self.prix_achat.value(),
                motif=self.motif.text(),
            )
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.show_lots()


class SupplierHistoryPage(QWidget):
    """Historique des livraisons d'un fournisseur.

    Alimentée par `LotService.supplier_history()` : seules les livraisons (stock initial
    et entrées d'approvisionnement) des lots fournis par ce fournisseur sont listées.
    """

    def __init__(self, win: MainWindow, supplier_id: int, supplier_nom: str) -> None:
        super().__init__()
        self.win = win
        self._supplier_id = supplier_id
        self._all: list[SupplierMovement] = []
        self._displayed: list[SupplierMovement] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(make_label(f"Historique : {supplier_nom}", "title"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (produit, code, n° de lot)…")
        self.search.textChanged.connect(lambda _text: self._filter())
        layout.addWidget(self.search)

        self.table = make_table([
            "Date", "Type", "Produit", "N° de lot", "Péremption",
            "Quantité", "Utilisateur", "Motif",
        ])
        layout.addWidget(self.table, 1)

        self.count_label = make_label("", "muted")
        layout.addWidget(self.count_label)

        try:
            self._all = win.lots.supplier_history(win.ctx, supplier_id)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            self._all = []
        self._filter()

        back = make_button("Retour aux fournisseurs", "secondary")
        back.clicked.connect(lambda _checked=False: win.show_suppliers())
        row_layout = QHBoxLayout()
        row_layout.addWidget(back)
        row_layout.addStretch(1)
        layout.addLayout(row_layout)

    def _filter(self) -> None:
        needle = self.search.text().strip().lower()
        if needle:
            self._displayed = [
                m for m in self._all
                if needle in m.product_nom.lower()
                or needle in m.product_code.lower()
                or needle in m.lot_numero.lower()
            ]
        else:
            self._displayed = list(self._all)

        self.table.setRowCount(len(self._displayed))
        for row, m in enumerate(self._displayed):
            sign = "+" if m.quantite_signee > 0 else "−"
            fill_row(
                self.table,
                row,
                [
                    format_local(m.created_at),
                    MOVEMENT_LABELS.get(m.type, m.type),
                    f"{m.product_code} : {m.product_nom}",
                    m.lot_numero,
                    format_date(m.lot_date_peremption),
                    f"{sign}{abs(m.quantite_signee)}",
                    m.user_nom,
                    m.motif or "",
                ],
                foreground=ROSE_DARK if m.quantite_signee < 0 else None,
                right=(5,),
            )
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.count_label.setText(f"{len(self._displayed)} mouvement(s)")