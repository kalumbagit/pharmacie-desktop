"""Pages produits : liste avec recherche, formulaire de création / modification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
    QCompleter
)
from dataclasses import replace
from app.core.enums import Forme, SousUnite, UniteVente
from app.core.errors import AppError
from app.core.security import Permission
from app.core.utils import format_fcfa
from app.models import Product
from app.services.products import ProductInput
from app.ui.theme import (
    MUTED,
    CardPage,
    fill_row,
    fit_columns,
    make_button,
    make_label,
    make_spin,
    make_table,
    selected_index,
)

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_COLUMNS = [
    "Code",
    "Nom commercial",
    "Dosage",
    "Forme",
    "Catégorie",
    "Conditionnement",
    "Prix de vente",
    "Seuil min.",
    "Statut",
]

_SOUS_UNITES_PAR_FORME: dict[Forme, tuple[str, ...]] = {
    Forme.COMPRIME: ("Plaquette", "Comprimé"),
    Forme.GELULE: ("Plaquette", "Gélule"),
    Forme.SIROP: ("ml", "cl", "L"),
    Forme.SUSPENSION: ("ml", "cl"),
    Forme.SOLUTION_BUVABLE: ("ml", "cl"),
    Forme.INJECTABLE: ("Ampoule", "ml"),
    Forme.POMMADE: ("g", "Application"),
    Forme.CREME: ("g", "Application"),
    Forme.GEL: ("g", "Application"),
    Forme.POUDRE: ("g", "Sachet", "Dose"),
    Forme.SUPPOSITOIRE: ("Suppositoire",),
    Forme.OVULE: ("Ovule",),
    Forme.COLLYRE: ("ml", "Goutte"),
    Forme.GOUTTES: ("ml", "Goutte"),
    Forme.SPRAY: ("Bouffée", "Dose"),
    Forme.PATCH: ("Patch",),
    Forme.AMPOULE: ("Ampoule", "ml"),
}
_STATUS_FILTERS = [("Actifs", "ACTIF"), ("Inactifs", "INACTIF"), ("Tous", None)]


class ProductsPage(QWidget):
    def __init__(self, win: MainWindow) -> None:
        super().__init__()
        self.win = win
        self._products: list[Product] = []
        can_edit = win.ctx.has(Permission.PRODUCTS_EDIT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(make_label("Produits", "title"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (code, nom, code-barres, dosage)…")
        self.status_filter = QComboBox()
        for label, value in _STATUS_FILTERS:
            self.status_filter.addItem(label, value)
        self.btn_new = make_button("Nouveau produit")
        self.btn_edit = make_button("Modifier", "secondary")
        self.btn_toggle = make_button("Désactiver", "secondary")
        self.btn_new.clicked.connect(lambda _checked=False: win.show_product_form(None))
        self.btn_edit.clicked.connect(lambda _checked=False: self._edit())
        self.btn_toggle.clicked.connect(lambda _checked=False: self._toggle())
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
        layout.addLayout(bar)

        self.table = make_table(_COLUMNS)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        if can_edit:
            self.table.itemDoubleClicked.connect(lambda _item: self._edit())
        layout.addWidget(self.table, 1)
        self.count_label = make_label("", "muted")
        layout.addWidget(self.count_label)

        self.reload()

    def reload(self) -> None:
        index = selected_index(self.table)
        selected_id = self._products[index].id if index is not None else None
        try:
            self._products = self.win.products.list_products(
                self.win.ctx, self.search.text(), self.status_filter.currentData()
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        self.table.setRowCount(len(self._products))
        for row, p in enumerate(self._products):
            conditionnement = (
                f"1 {p.unite_vente} = {p.sous_unites_par_unite} {p.sous_unite}"
                if p.has_sous_unite
                else p.unite_vente
            )
            cells = [
                p.code,
                p.nom_commercial,
                p.dosage or "",
                p.forme or "",
                p.categorie or "",
                conditionnement,
                format_fcfa(p.prix_vente),
                p.format_quantity(p.seuil_minimal),
                "Actif" if p.is_active else "Désactivé",
            ]
            fill_row(
                self.table,
                row,
                cells,
                foreground=None if p.is_active else MUTED,
                right=(6,),
            )
            if p.id == selected_id:
                self.table.selectRow(row)
        fit_columns(self.table, 1)
        self.count_label.setText(f"{len(self._products)} produit(s)")
        self._update_buttons()

    def _selected(self) -> Product | None:
        index = selected_index(self.table)
        return self._products[index] if index is not None else None

    def _update_buttons(self) -> None:
        product = self._selected()
        self.btn_edit.setEnabled(product is not None)
        self.btn_toggle.setEnabled(product is not None)
        inactive = product is not None and not product.is_active
        self.btn_toggle.setText("Réactiver" if inactive else "Désactiver")

    def _edit(self) -> None:
        product = self._selected()
        if product is not None:
            self.win.show_product_form(product)

    def _toggle(self) -> None:
        product = self._selected()
        if product is None:
            return
        activate = not product.is_active
        if not activate:
            answer = QMessageBox.question(
                self,
                "Désactiver le produit",
                f"Désactiver « {product.nom_commercial} » ?\n"
                "Il ne pourra plus être réceptionné ni vendu.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.win.products.set_active(self.win.ctx, product.id, activate)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        self.reload()


class ProductFormPage(CardPage):
    """Création (product=None) ou modification d'un produit."""

    def __init__(self, win: MainWindow, product: Product | None = None) -> None:
        super().__init__(
            "Modifier le produit" if product else "Nouveau produit",
            "Le stock est compté dans la plus petite unité : la sous-unité si elle existe, "
            "sinon l'unité de vente.",
            width=620,
        )
        self.win = win
        self._product = product
        can_price = win.ctx.has(Permission.PRICE_EDIT)

        self.barcode = QLineEdit(product.code_barres or "" if product else "")
        self.nom = QLineEdit(product.nom_commercial if product else "")
        self.description = QLineEdit(product.description or "" if product else "")
        self.dosage = QLineEdit(product.dosage or "" if product else "")

        # Catégorie : reste un QComboBox éditable (table libre).
        # Catégorie : QComboBox éditable avec autocomplétion « contient ».
        # → Taper « pa » filtre les catégories contenant « pa » (ex. Antalgique, Antiparasitaire).
        self.categorie = QComboBox()
        self.categorie.setEditable(True)
        self.categorie.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        try:
            self.categorie.addItems(win.products.list_categories(win.ctx))
        except AppError as exc:
            self.set_error(str(exc))
        _completer_cat = self.categorie.completer()
        if _completer_cat is not None:
            _completer_cat.setFilterMode(Qt.MatchFlag.MatchContains)
            _completer_cat.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            _completer_cat.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.categorie.setCurrentText(product.categorie or "" if product else "")

        # Forme : QComboBox non éditable (énumération fermée).
        self.forme = QComboBox()
        self.forme.addItem("")  # option vide = aucune forme
        try:
            self.categorie.addItems(win.products.list_categories(win.ctx))
            self.forme.addItems(win.products.list_formes(win.ctx))
        except AppError as exc:
            self.set_error(str(exc))
        self.categorie.setCurrentText(product.categorie or "" if product else "")
        if product and product.forme:
            self.forme.setCurrentText(product.forme)

        # Unité de vente : QComboBox non éditable (énumération fermée).
        self.unite = QComboBox()
        self.unite.addItems(win.products.list_unites(win.ctx))
        self.unite.setCurrentText(
            product.unite_vente if product else UniteVente.BOITE.value
        )

        # Sous-unité : QComboBox éditable (filtrage dynamique par forme + saisie libre).
        self.sous_unite = QComboBox()
        self.sous_unite.setEditable(True)
        self.sous_unite.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sous_unite.lineEdit().setPlaceholderText(
            "ex. Plaquette (laisser vide si aucune)"
        )
        self.sous_unite.addItem("")  # option vide = pas de sous-unité
        try:
            self.sous_unite.addItems(win.products.list_sous_unites(win.ctx))
        except AppError as exc:
            self.set_error(str(exc))
        self.sous_unite.setCurrentText(product.sous_unite or "" if product else "")

        self.par_unite = make_spin(1000, minimum=1)
        self.par_unite.setValue(product.sous_unites_par_unite if product else 1)

        self.prix_vente = make_spin(suffix=" FCFA")
        self.prix_vente.setValue(product.prix_vente if product else 0)
        self.prix_sous_unite = make_spin(suffix=" FCFA")
        self.prix_sous_unite.setValue(product.prix_vente_sous_unite or 0 if product else 0)
        self.seuil = make_spin(1_000_000)
        self.seuil.setValue(product.seuil_minimal if product else 0)
        self.seuil_hint = make_label("", "muted")

        self.form.addRow("Code-barres", self.barcode)
        self.form.addRow("Nom commercial *", self.nom)
        self.form.addRow("Description", self.description)
        self.form.addRow("Catégorie", self.categorie)
        self.form.addRow("Forme", self.forme)
        self.form.addRow("Dosage", self.dosage)
        self.form.addRow("Unité de vente *", self.unite)
        self.form.addRow("Sous-unité", self.sous_unite)
        self.form.addRow("Sous-unités par unité", self.par_unite)
        self.form.addRow("Prix de vente (unité)", self.prix_vente)
        self.form.addRow("Prix de vente (sous-unité)", self.prix_sous_unite)
        self.form.addRow("Seuil minimal de stock", self.seuil)
        self.form.addRow("", self.seuil_hint)

        # Les prix ne se modifient qu'avec la permission « price.edit » (contrôlée aussi
        # dans le service).
        for field in (self.prix_vente, self.prix_sous_unite):
            field.setEnabled(can_price)

        # Conditionnement figé dès que le produit possède des lots.
        self._packaging_locked = False
        if product is not None:
            try:
                self._packaging_locked = win.products.has_lots(win.ctx, product.id)
            except AppError:
                self._packaging_locked = True
        if self._packaging_locked:
            self.sous_unite.setEnabled(False)
            self.par_unite.setEnabled(False)
            self.body.insertWidget(
                self.body.indexOf(self.error),
                make_label(
                    "Le conditionnement ne peut plus changer : ce produit possède déjà des lots.",
                    "muted",
                ),
            )

        self.sous_unite.currentTextChanged.connect(lambda _text: self._refresh_packaging())
        # QComboBox n'a pas de signal « textChanged » : utiliser currentTextChanged.
        self.unite.currentTextChanged.connect(lambda _text: self._refresh_packaging())
        self.par_unite.valueChanged.connect(lambda _value: self._refresh_packaging())
        # Filtrage dynamique des sous-unités selon la forme sélectionnée.
        self.forme.currentTextChanged.connect(lambda _text: self._refresh_sous_unites())

        # Initialisation : filtre selon la forme courante + mise à jour du hint.
        self._refresh_sous_unites()

        save = make_button("Enregistrer")
        save.clicked.connect(lambda _checked=False: self._submit())
        cancel = make_button("Annuler", "secondary")
        cancel.clicked.connect(lambda _checked=False: win.show_products())
        self.add_buttons(cancel, save)

    def _refresh_sous_unites(self) -> None:
        """Filtre les suggestions de sous-unité selon la forme sélectionnée.

        Le combo reste éditable : l'utilisateur peut saisir une valeur hors liste.
        """
        forme_text = self.forme.currentText().strip()
        try:
            forme = Forme(forme_text) if forme_text else None
        except ValueError:
            forme = None

        # On mémorise la saisie courante pour la restaurer après filtrage.
        current = self.sous_unite.currentText()

        self.sous_unite.blockSignals(True)
        self.sous_unite.clear()
        self.sous_unite.addItem("")  # option vide
        if forme is not None:
            suggestions = _SOUS_UNITES_PAR_FORME.get(forme, SousUnite.values())
        else:
            suggestions = SousUnite.values()
        self.sous_unite.addItems(suggestions)
        self.sous_unite.setCurrentText(current)  # conserve la saisie si toujours valide
        self.sous_unite.blockSignals(False)

        # Signaux bloqués pendant le repopulate : on rafraîchit manuellement le hint.
        self._refresh_packaging()

    def _refresh_packaging(self) -> None:
        has_sub = bool(self.sous_unite.currentText().strip())
        if not self._packaging_locked:
            self.par_unite.setEnabled(has_sub)
        self.prix_sous_unite.setEnabled(has_sub and self.win.ctx.has(Permission.PRICE_EDIT))
        base = (
            self.sous_unite.currentText().strip()
            if has_sub
            else self.unite.currentText().strip()
        )
        self.seuil_hint.setText(f"Exprimé en « {base or '…'} » (plus petite unité).")

    def _submit(self) -> None:
        # Conversion des widgets vers les énumérations typées.
        try:
            unite = UniteVente(self.unite.currentText())
        except ValueError:
            self.set_error("Unité de vente invalide.")
            return

        forme_text = self.forme.currentText().strip()
        try:
            forme = Forme(forme_text) if forme_text else None
        except ValueError:
            self.set_error("Forme invalide.")
            return

        data = ProductInput(
            nom_commercial=self.nom.text(),
            unite_vente=unite,
            code_barres=self.barcode.text(),
            description=self.description.text(),
            categorie=self.categorie.currentText(),
            forme=forme,
            dosage=self.dosage.text(),
            sous_unite=self.sous_unite.currentText(),
            sous_unites_par_unite=self.par_unite.value(),
            prix_vente=self.prix_vente.value(),
            prix_vente_sous_unite=self.prix_sous_unite.value(),
            seuil_minimal=self.seuil.value(),
        )
        try:
            if self._product is None:
                self.win.products.create_product(self.win.ctx, data)
            else:
                data = replace(data, code=self._product.code)
                self.win.products.update_product(self.win.ctx, self._product.id, data)
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.show_products()


