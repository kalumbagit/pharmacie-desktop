"""Caisse : ouverture, point de vente (panier, paiements), vente terminée, clôture."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.core.security import Permission
from app.core.utils import format_fcfa, format_local
from app.models import CashSession, Product
from app.services.cash import SessionSummary
from app.services.sales import (
    CartItem,
    PaymentInput,
    Quote,
    SaleResult,
    SellableProduct,
)
from app.ui.theme import (
    ROSE_DARK,
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


def open_pdf(parent: QWidget, path: Path) -> None:
    """Ouvre le PDF dans le lecteur du système (d'où l'impression est possible)."""
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        QMessageBox.information(
            parent,
            "Document créé",
            f"Le PDF a été enregistré ici :\n{path}",
        )


# ==================================================================================
# Ouverture de la caisse
# ==================================================================================

class CashOpenPage(CardPage):
    def __init__(self, win: MainWindow) -> None:
        super().__init__(
            "Ouvrir la caisse",
            "Indiquez le fond de caisse (espèces présentes dans le tiroir) pour commencer.",
        )

        self.win = win
        self.fond = make_spin(suffix=" FCFA")
        self.form.addRow("Fond de caisse", self.fond)

        button = make_button("Ouvrir la caisse")
        button.clicked.connect(lambda _checked=False: self._submit())

        self.add_buttons(button)
        self.fond.setFocus()

    def _submit(self) -> None:
        try:
            self.win.cash.open_session(
                self.win.ctx,
                self.fond.value(),
            )
        except AppError as exc:
            self.set_error(str(exc))
            return

        self.win.show_cash()


# ==================================================================================
# Point de vente
# ==================================================================================

@dataclass
class CartLine:
    product: Product
    conditionnement: str
    quantite: int = 1
    remise: int = 0

    @property
    def unite(self) -> str:
        if self.conditionnement == "SOUS_UNITE":
            return self.product.sous_unite or ""

        return self.product.unite_vente

    @property
    def prix(self) -> int:
        if self.conditionnement == "SOUS_UNITE":
            return self.product.prix_vente_sous_unite or 0

        return self.product.prix_vente


class CashPage(QWidget):
    """Point de vente : recherche à gauche, panier et paiement à droite."""

    def __init__(self, win: MainWindow, session: CashSession) -> None:
        super().__init__()

        self.win = win
        self.session = session
        self.token = uuid.uuid4().hex
        self.cart: list[CartLine] = []
        self._results: list[SellableProduct] = []
        self._quote: Quote | None = None
        self._methods: list[tuple[str, str]] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        root.addWidget(self._build_search_panel(), 6)
        root.addWidget(self._build_cart_panel(), 5)

        self._load_methods()
        self._search()
        self._refresh()
        self.search.setFocus()

    # --- Construction --------------------------------------------------------------

    def _build_search_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)

        layout.addWidget(make_label("Produits", "sectionTitle"))

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Nom, code ou scan du code-barres (Entrée)…"
        )
        self.search.textChanged.connect(
            lambda _text: self._search()
        )
        self.search.returnPressed.connect(self._enter_pressed)
        layout.addWidget(self.search)

        # Par défaut, seuls les produits en stock vendable sont proposés.
        self.show_out_of_stock = QCheckBox("Afficher les produits en rupture")
        self.show_out_of_stock.toggled.connect(lambda _checked: self._search())
        layout.addWidget(self.show_out_of_stock)

        self.results = make_table(
            ["Produit", "Prix", "Stock"],
            stretch_column=0,
        )
        self.results.itemDoubleClicked.connect(
            lambda _item: self._add_selected("UNITE")
        )
        layout.addWidget(self.results, 1)

        row = QHBoxLayout()

        self.btn_add = make_button("Ajouter")
        self.btn_add_sub = make_button(
            "Ajouter (sous-unité)",
            "secondary",
        )

        self.btn_add.clicked.connect(
            lambda _checked=False: self._add_selected("UNITE")
        )
        self.btn_add_sub.clicked.connect(
            lambda _checked=False: self._add_selected("SOUS_UNITE")
        )

        row.addWidget(self.btn_add)
        row.addWidget(self.btn_add_sub)

        layout.addLayout(row)

        self.results.itemSelectionChanged.connect(
            self._update_add_buttons
        )

        return panel

    def _build_cart_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("pagescroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(make_label("Panier", "sectionTitle"), 1)

        self.btn_close_cash = make_button("Clôturer la caisse")
        self.btn_close_cash.clicked.connect(
            lambda _checked=False: self.win.show_cash_close()
        )
        head.addWidget(self.btn_close_cash)
        layout.addLayout(head)

        self.cart_table = make_table(
            ["Produit", "Cond.", "Qté", "Prix", "Remise", "Total"],
            stretch_column=0,
        )
        self.cart_table.setMinimumHeight(170)
        self.cart_table.itemSelectionChanged.connect(
            self._update_cart_buttons
        )
        layout.addWidget(self.cart_table, 1)

        tools = QHBoxLayout()

        self.btn_plus = make_button("+", "secondary")
        self.btn_minus = make_button("−", "secondary")
        self.btn_qty = make_button("Quantité…", "secondary")
        self.btn_discount = make_button("Remise…", "secondary")
        self.btn_remove = make_button("Retirer", "secondary")
        self.btn_clear = make_button("Vider", "secondary")

        self.btn_plus.clicked.connect(lambda _c=False: self._change_qty(1))
        self.btn_minus.clicked.connect(lambda _c=False: self._change_qty(-1))
        self.btn_qty.clicked.connect(lambda _c=False: self._ask_qty())
        self.btn_discount.clicked.connect(lambda _c=False: self._ask_discount())
        self.btn_remove.clicked.connect(lambda _c=False: self._remove())
        self.btn_clear.clicked.connect(lambda _c=False: self._clear())

        for button in (
            self.btn_plus, self.btn_minus, self.btn_qty,
            self.btn_discount, self.btn_remove, self.btn_clear,
        ):
            tools.addWidget(button)
        layout.addLayout(tools)

        # ------------------------------------------------------------------
        # Totaux
        # ------------------------------------------------------------------
        totals = QGridLayout()
        totals.setHorizontalSpacing(12)

        self.lbl_brut = make_label("0 FCFA")
        self.lbl_taxe_title = make_label("Taxe")
        self.lbl_taxe = make_label("0 FCFA")

        self.discount = make_spin(suffix=" FCFA")
        self.discount.valueChanged.connect(lambda _v: self._refresh())

        self.lbl_net = make_label("0 FCFA", "bigTotal")

        totals.addWidget(make_label("Montant brut"), 0, 0)
        totals.addWidget(self.lbl_brut, 0, 1)
        totals.addWidget(make_label("Remise globale"), 1, 0)
        totals.addWidget(self.discount, 1, 1)
        totals.addWidget(self.lbl_taxe_title, 2, 0)
        totals.addWidget(self.lbl_taxe, 2, 1)
        totals.addWidget(make_label("NET À PAYER", "sectionTitle"), 3, 0)
        totals.addWidget(self.lbl_net, 3, 1)
        layout.addLayout(totals)

        # ------------------------------------------------------------------
        # Paiement immédiat — saisi ici, traité à la validation
        # ------------------------------------------------------------------
        pay = QGridLayout()
        pay.setHorizontalSpacing(12)
        pay.setVerticalSpacing(6)
        pay.setColumnStretch(1, 1)

        pay.addWidget(make_label("Mode de paiement", "muted"), 0, 0)
        pay.addWidget(make_label("Montant perçu", "muted"), 0, 1)

        self.method = QComboBox()

        self.pay_amount = make_spin(suffix=" FCFA")
        self.pay_amount.setToolTip(
            "Montant remis par le client. Doit couvrir la totalité du net à payer."
        )
        self.pay_amount.valueChanged.connect(lambda _v: self._refresh())

        self.btn_exact = make_button("Montant exact", "secondary")
        self.btn_exact.clicked.connect(
            lambda _checked=False: self._fill_exact()
        )

        pay.addWidget(self.method, 1, 0)
        pay.addWidget(self.pay_amount, 1, 1)
        pay.addWidget(self.btn_exact, 1, 2)
        layout.addLayout(pay)

        # ------------------------------------------------------------------
        # Contrôle du règlement : insuffisant / monnaie à rendre
        # ------------------------------------------------------------------
        self.lbl_reste = make_label("", "error")
        self.lbl_change = make_label("", "bigChange")

        change_row = QHBoxLayout()
        change_row.setSpacing(8)
        change_row.addWidget(make_label("Monnaie à rendre", "muted"))
        change_row.addWidget(self.lbl_change, 1)

        layout.addWidget(self.lbl_reste)
        layout.addLayout(change_row)

        # Récapitulatif (informatif, rempli par _refresh / _validate)
        self.lbl_payments = make_label("", "muted")
        self.lbl_payments.setWordWrap(True)
        layout.addWidget(self.lbl_payments)

        # ------------------------------------------------------------------
        # Client (facultatif)
        # ------------------------------------------------------------------
        client = QHBoxLayout()

        self.client_nom = QLineEdit()
        self.client_nom.setPlaceholderText("Nom du client (optionnel)")

        self.client_tel = QLineEdit()
        self.client_tel.setPlaceholderText("Téléphone (optionnel)")

        client.addWidget(self.client_nom, 3)
        client.addWidget(self.client_tel, 2)
        layout.addLayout(client)

        self.error = make_label("", "error")
        layout.addWidget(self.error)

        self.btn_validate = make_button("Valider la vente")
        self.btn_validate.clicked.connect(
            lambda _checked=False: self._validate()
        )
        layout.addWidget(self.btn_validate)

        return panel

    # --- Recherche -----------------------------------------------------------------

    def _search(self) -> None:
        try:
            self._results = self.win.sales.search_products(
                self.win.ctx,
                self.search.text(),
                include_out_of_stock=self.show_out_of_stock.isChecked(),
            )
        except AppError as exc:
            self.error.setText(str(exc))
            return

        self.results.setRowCount(len(self._results))

        for row, item in enumerate(self._results):
            p = item.product

            prix = format_fcfa(p.prix_vente)

            if p.has_sous_unite:
                prix += (
                    f" / {format_fcfa(p.prix_vente_sous_unite or 0)}"
                    f" ({p.sous_unite})"
                )

            label = p.nom_commercial

            if p.dosage:
                label += f" {p.dosage}"

            stock = (
                p.format_quantity(item.stock_base)
                if item.stock_base
                else "Rupture"
            )

            fill_row(
                self.results,
                row,
                [label, prix, stock],
                foreground=None if item.stock_base else ROSE_DARK,
                right=(1,),
            )

        fit_columns(self.results, 0)
        self._update_add_buttons()

    def _selected_product(self) -> SellableProduct | None:
        index = selected_index(self.results)

        return (
            self._results[index]
            if index is not None
            else None
        )

    def _update_add_buttons(self) -> None:
        item = self._selected_product()

        in_stock = item is not None and item.stock_base > 0
        self.btn_add.setEnabled(in_stock)
        self.btn_add_sub.setEnabled(
            in_stock and item is not None and item.product.has_sous_unite
        )

    def _enter_pressed(self) -> None:
        """Entrée : code-barres / code exact → ajout direct ; sinon 1er résultat."""
        text = self.search.text()

        try:
            product = self.win.sales.find_exact(
                self.win.ctx,
                text,
            )
        except AppError as exc:
            self.error.setText(str(exc))
            return

        if product is None and self._results:
            product = self._results[0].product

        if product is not None:
            self._add_product(product, "UNITE")
            self.search.clear()

    def _add_selected(self, conditionnement: str) -> None:
        item = self._selected_product()

        if item is not None and item.stock_base > 0:
            self._add_product(
                item.product,
                conditionnement,
            )

    # --- Panier --------------------------------------------------------------------

    def _add_product(
        self,
        product: Product,
        conditionnement: str,
    ) -> None:
        if (
            conditionnement == "SOUS_UNITE"
            and not product.has_sous_unite
        ):
            return

        for line in self.cart:
            if (
                line.product.id == product.id
                and line.conditionnement == conditionnement
            ):
                line.quantite += 1
                break
        else:
            self.cart.append(
                CartLine(product, conditionnement)
            )

        self._refresh()

    def _selected_line(self) -> CartLine | None:
        index = selected_index(self.cart_table)

        return (
            self.cart[index]
            if index is not None and index < len(self.cart)
            else None
        )

    def _change_qty(self, delta: int) -> None:
        line = self._selected_line()

        if line is None:
            return

        line.quantite = max(1, line.quantite + delta)

        self._refresh(
            keep=self.cart.index(line)
        )

    def _ask_qty(self) -> None:
        line = self._selected_line()

        if line is None:
            return

        value, ok = QInputDialog.getInt(
            self,
            "Quantité",
            f"Quantité ({line.unite}) :",
            line.quantite,
            1,
            100_000,
        )

        if ok:
            line.quantite = value
            self._refresh(
                keep=self.cart.index(line)
            )

    def _ask_discount(self) -> None:
        line = self._selected_line()

        if line is None:
            return

        value, ok = QInputDialog.getInt(
            self,
            "Remise de ligne",
            "Remise sur cette ligne (FCFA) :",
            line.remise,
            0,
            100_000_000,
        )

        if ok:
            line.remise = value
            self._refresh(
                keep=self.cart.index(line)
            )

    def _remove(self) -> None:
        line = self._selected_line()

        if line is not None:
            self.cart.remove(line)
            self._refresh()

    def _clear(self) -> None:
        self.cart.clear()
        self.pay_amount.setValue(0)
        self.discount.setValue(0)
        self._refresh()

    def _items(self) -> list[CartItem]:
        return [
            CartItem(
                line.product.id,
                line.quantite,
                line.conditionnement,
                line.remise,
            )
            for line in self.cart
        ]

    def _update_cart_buttons(self) -> None:
        has = self._selected_line() is not None

        for button in (
            self.btn_plus,
            self.btn_minus,
            self.btn_qty,
            self.btn_discount,
            self.btn_remove,
        ):
            button.setEnabled(has)

    # --- Paiements -----------------------------------------------------------------

    def _load_methods(self) -> None:
        try:
            methods = self.win.sales.payment_methods(
                self.win.ctx
            )
        except AppError as exc:
            self.error.setText(str(exc))
            methods = []

        self._methods = [
            (method.code, method.libelle)
            for method in methods
        ]

        for code, label in self._methods:
            self.method.addItem(label, code)

    def _tendered(self) -> int:
        """Montant perçu : celui saisi dans le champ « Montant perçu »."""
        return self.pay_amount.value()

    def _fill_exact(self) -> None:
        self.pay_amount.setValue(self._quote.net if self._quote else 0)

    # --- Affichage -----------------------------------------------------------------

    def _refresh(self, keep: int | None = None) -> None:
        self.error.setText("")

        try:
            self._quote = self.win.sales.quote(
                self.win.ctx,
                self._items(),
                self.discount.value(),
            )
        except AppError as exc:
            self._quote = None
            self.error.setText(str(exc))

        self.cart_table.setRowCount(len(self.cart))

        for row, line in enumerate(self.cart):
            fill_row(
                self.cart_table,
                row,
                [
                    line.product.nom_commercial,
                    line.unite,
                    str(line.quantite),
                    format_fcfa(line.prix),
                    format_fcfa(line.remise) if line.remise else "",
                    format_fcfa(
                        line.quantite * line.prix - line.remise
                    ),
                ],
                right=(2, 3, 4, 5),
            )

        fit_columns(self.cart_table, 0)

        if keep is not None and keep < len(self.cart):
            self.cart_table.selectRow(keep)

        quote = self._quote
        net = quote.net if quote else 0

        self.lbl_brut.setText(
            format_fcfa(quote.brut if quote else 0)
        )
        self.lbl_net.setText(format_fcfa(net))

        taux = quote.taux_taxe_bp if quote else 0

        self.lbl_taxe_title.setText(
            f"Taxe ({taux / 100:g} %)"
            if taux
            else "Taxe"
        )

        self.lbl_taxe.setText(
            format_fcfa(quote.taxes if quote else 0)
        )

        tendered = self._tendered()

        self.lbl_payments.setText(
            f"{self.method.currentText()} : {format_fcfa(tendered)}"
            if tendered > 0 and self.method.currentIndex() >= 0
            else "Aucun paiement saisi."
        )

        self.lbl_reste.setText(
            f"Reste à payer : {format_fcfa(max(0, net - tendered))}"
        )

        change = tendered - net

        self.lbl_change.setText(
            f"Monnaie à rendre : {format_fcfa(change)}"
            if change > 0
            else ""
        )

        self.btn_validate.setEnabled(
            bool(self.cart) and quote is not None
        )

        self._update_cart_buttons()

    # --- Validation ----------------------------------------------------------------

    def _validate(self) -> None:
        payments = (
            [PaymentInput(self.method.currentData(), self.pay_amount.value())]
            if self.pay_amount.value() > 0 and self.method.currentIndex() >= 0
            else []
        )

        try:
            result = self.win.sales.validate_sale(
                self.win.ctx,
                token=self.token,
                items=self._items(),
                payments=payments,
                remise_globale=self.discount.value(),
                client_nom=self.client_nom.text(),
                client_telephone=self.client_tel.text(),
            )
        except AppError as exc:
            self.error.setText(str(exc))
            return

        self.win.show_sale_done(result)


# ==================================================================================
# Vente terminée : facture ou simple validation
# ==================================================================================

class SaleDonePage(CardPage):
    def __init__(
        self,
        win: MainWindow,
        result: SaleResult,
    ) -> None:
        sale = result.sale

        super().__init__(
            "Vente enregistrée",
            f"N° {sale.numero_vente}"
            + (
                "  (déjà enregistrée)"
                if result.deja_traitee
                else ""
            ),
            width=520,
        )

        self.win = win
        self.result = result

        self.form.addRow(
            "Net à payer",
            make_label(format_fcfa(sale.montant_net)),
        )

        self.form.addRow(
            "Payé",
            make_label(format_fcfa(sale.montant_paye)),
        )

        if sale.reste:
            reste = make_label(
                format_fcfa(sale.reste),
                "error",
            )
            self.form.addRow("Reste à payer", reste)

        if result.monnaie:
            self.body.insertWidget(
                self.body.indexOf(self.error),
                make_label(
                    f"Monnaie à rendre : {format_fcfa(result.monnaie)}",
                    "bigChange",
                ),
            )

        can_invoice = win.ctx.has(
            Permission.INVOICES_GENERATE
        )

        self.client_nom = QLineEdit(sale.client_nom or "")
        self.client_nom.setPlaceholderText(
            "Nom du client (facultatif)"
        )

        self.client_tel = QLineEdit(
            sale.client_telephone or ""
        )
        self.client_tel.setPlaceholderText(
            "Téléphone (facultatif)"
        )

        if can_invoice:
            self.form.addRow(
                "Client (facture)",
                self.client_nom,
            )
            self.form.addRow(
                "Téléphone",
                self.client_tel,
            )

        new = make_button("Nouvelle vente")
        new.clicked.connect(
            lambda _checked=False: win.show_cash()
        )

        buttons = [new]

        if can_invoice:
            invoice = make_button(
                "Facture PDF",
                "secondary",
            )
            receipt = make_button(
                "Reçu PDF",
                "secondary",
            )

            invoice.clicked.connect(
                lambda _checked=False: self._invoice()
            )
            receipt.clicked.connect(
                lambda _checked=False: self._receipt()
            )

            buttons = [receipt, invoice, new]

        self.add_buttons(*buttons)

    def _invoice(self) -> None:
        try:
            _invoice, path = self.win.invoices.generate_invoice(
                self.win.ctx,
                self.result.sale.id,
                self.client_nom.text(),
                self.client_tel.text(),
            )
        except AppError as exc:
            self.set_error(str(exc))
            return

        self.set_error("")
        open_pdf(self, path)

    def _receipt(self) -> None:
        try:
            path = self.win.invoices.generate_receipt(
                self.win.ctx,
                self.result.sale.id,
                self.result.monnaie,
            )
        except AppError as exc:
            self.set_error(str(exc))
            return

        self.set_error("")
        open_pdf(self, path)


# ==================================================================================
# Clôture de la caisse
# ==================================================================================

class CashClosePage(CardPage):
    def __init__(
        self,
        win: MainWindow,
        summary: SessionSummary,
    ) -> None:
        super().__init__(
            "Clôturer la caisse",
            f"Session ouverte le {format_local(summary.session.ouverte_le)}.",
            width=520,
        )

        self.win = win
        self.summary = summary

        self.form.addRow(
            "Ventes validées",
            make_label(str(summary.nombre_ventes)),
        )

        self.form.addRow(
            "Fond de caisse",
            make_label(
                format_fcfa(summary.session.fond_ouverture)
            ),
        )

        for total in summary.totaux:
            self.form.addRow(
                str(total["libelle"]),
                make_label(format_fcfa(int(total["net"]))),
            )

        self.form.addRow(
            "Espèces attendues",
            make_label(format_fcfa(summary.montant_attendu)),
        )

        self.counted = make_spin(suffix=" FCFA")
        self.counted.setValue(summary.montant_attendu)
        self.counted.valueChanged.connect(
            lambda _value: self._update_gap()
        )

        self.form.addRow(
            "Espèces comptées",
            self.counted,
        )

        self.gap = make_label("")
        self.form.addRow("Écart", self.gap)

        self._update_gap()

        cancel = make_button(
            "Retour à la caisse",
            "secondary",
        )
        cancel.clicked.connect(
            lambda _checked=False: win.show_cash()
        )

        close = make_button("Clôturer", "danger")
        close.clicked.connect(
            lambda _checked=False: self._close()
        )

        self.add_buttons(cancel, close)

    def _update_gap(self) -> None:
        gap = (
            self.counted.value()
            - self.summary.montant_attendu
        )

        self.gap.setText(
            format_fcfa(gap)
            if gap
            else "Aucun écart"
        )

        self.gap.setObjectName(
            "error" if gap else "muted"
        )

        self.gap.style().unpolish(self.gap)
        self.gap.style().polish(self.gap)

    def _close(self) -> None:
        try:
            closed = self.win.cash.close_session(
                self.win.ctx,
                self.summary.session.id,
                self.counted.value(),
            )
        except AppError as exc:
            self.set_error(str(exc))
            return

        gap = closed.ecart or 0

        QMessageBox.information(
            self,
            "Caisse clôturée",
            "Caisse clôturée."
            + (
                f"\nÉcart constaté : {format_fcfa(gap)}"
                if gap
                else "\nAucun écart."
            ),
        )

        self.win.show_home()