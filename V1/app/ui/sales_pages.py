"""Historique des ventes : liste par jour, détail, encaissement du solde, annulation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.core.security import Permission
from app.core.utils import format_fcfa, format_local
from app.models import Sale
from app.ui.cash_pages import open_pdf
from app.ui.theme import (
    MUTED,
    ROSE_DARK,
    ROSE_LIGHT,
    fill_row,
    fit_columns,
    make_button,
    make_date_edit,
    make_label,
    make_table,
    selected_index,
)

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_COLUMNS = ["N° de vente", "Heure", "Vendeur", "Client", "Net", "Payé", "Reste", "Statut"]


def _status(sale: Sale) -> str:
    if sale.is_cancelled:
        return "Annulée"
    return "À crédit" if sale.reste > 0 else "Soldée"


class SalesPage(QWidget):
    """Ventes d'un jour : toutes (pharmacien, administrateur) ou les siennes (caissier)."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__()
        self.win = win
        self._sales: list[Sale] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(make_label("Ventes", "title"))

        self.day = make_date_edit()
        self.day.dateChanged.connect(lambda _date: self.reload())
        self.btn_detail = make_button("Détails")
        self.btn_invoice = make_button("Facture PDF", "secondary")
        self.btn_receipt = make_button("Reçu PDF", "secondary")
        self.btn_detail.clicked.connect(lambda _checked=False: self._detail())
        self.btn_invoice.clicked.connect(lambda _checked=False: self._invoice())
        self.btn_receipt.clicked.connect(lambda _checked=False: self._receipt())

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(make_label("Jour :"))
        bar.addWidget(self.day)
        bar.addStretch(1)
        bar.addWidget(self.btn_detail)
        if win.ctx.has(Permission.INVOICES_GENERATE):
            bar.addWidget(self.btn_invoice)
            bar.addWidget(self.btn_receipt)
        layout.addLayout(bar)

        self.table = make_table(_COLUMNS, stretch_column=3)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._detail())
        layout.addWidget(self.table, 1)
        self.summary = make_label("", "muted")
        layout.addWidget(self.summary)
        self.reload()

    def reload(self) -> None:
        index = selected_index(self.table)
        selected_id = self._sales[index].id if index is not None else None
        try:
            self._sales = self.win.sales.list_sales(
                self.win.ctx, self.day.date().toPython()
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        self.table.setRowCount(len(self._sales))
        for row, sale in enumerate(self._sales):
            fill_row(
                self.table,
                row,
                [
                    sale.numero_vente,
                    format_local(sale.date_vente)[-5:],
                    sale.user_nom,
                    sale.client_nom or "",
                    format_fcfa(sale.montant_net),
                    format_fcfa(sale.montant_paye),
                    format_fcfa(sale.reste) if sale.reste else "",
                    _status(sale),
                ],
                foreground=MUTED if sale.is_cancelled else (
                    ROSE_DARK if sale.reste else None
                ),
                background=(
                    ROSE_LIGHT if sale.reste and not sale.is_cancelled else None
                ),
                right=(4, 5, 6),
            )
            if sale.id == selected_id:
                self.table.selectRow(row)
        fit_columns(self.table, 3)

        valid = [s for s in self._sales if not s.is_cancelled]
        self.summary.setText(
            f"{len(valid)} vente(s) validée(s) pour "
            f"{format_fcfa(sum(s.montant_net for s in valid))}"
            + (
                f"  |  {len(self._sales) - len(valid)} annulée(s)"
                if len(valid) != len(self._sales)
                else ""
            )
        )
        self._update_buttons()

    def _selected(self) -> Sale | None:
        index = selected_index(self.table)
        return self._sales[index] if index is not None else None

    def _update_buttons(self) -> None:
        has = self._selected() is not None
        for button in (self.btn_detail, self.btn_invoice, self.btn_receipt):
            button.setEnabled(has)

    def _detail(self) -> None:
        sale = self._selected()
        if sale is not None:
            self.win.show_sale_detail(sale.id)

    def _invoice(self) -> None:
        sale = self._selected()
        if sale is None:
            return
        try:
            _invoice, path = self.win.invoices.generate_invoice(
                self.win.ctx, sale.id
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        open_pdf(self, path)

    def _receipt(self) -> None:
        sale = self._selected()
        if sale is None:
            return
        try:
            path = self.win.invoices.generate_receipt(self.win.ctx, sale.id)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        open_pdf(self, path)


class SaleDetailPage(QWidget):
    def __init__(self, win: MainWindow, sale_id: int) -> None:
        super().__init__()
        self.win = win
        self.sale_id = sale_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        try:
            details = win.sales.get_details(win.ctx, sale_id)
        except AppError as exc:
            layout.addWidget(make_label(str(exc), "error"))
            back = make_button("Retour aux ventes", "secondary")
            back.clicked.connect(lambda _checked=False: win.show_sales())
            layout.addWidget(back)
            layout.addStretch(1)
            return

        self.details = details
        sale = details.sale

        layout.addWidget(make_label(f"Vente {sale.numero_vente}", "title"))
        info = (
            f"{format_local(sale.date_vente)}  |  Vendeur : {sale.user_nom}"
            + (f"  |  Client : {sale.client_nom}" if sale.client_nom else "")
            + (f" ({sale.client_telephone})" if sale.client_telephone else "")
        )
        layout.addWidget(make_label(info, "muted"))

        if sale.is_cancelled:
            layout.addWidget(
                make_label(
                    f"VENTE ANNULÉE le {format_local(sale.annulee_le)} : "
                    f"{sale.motif_annulation}",
                    "error",
                )
            )

        lines = make_table(
            ["Produit", "Lot", "Qté", "Prix unitaire", "Remise", "Montant"],
            stretch_column=0,
        )
        lines.setRowCount(len(details.lines))
        for row, line in enumerate(details.lines):
            fill_row(
                lines,
                row,
                [
                    f"{line.product_code} : {line.product_nom}",
                    line.numero_lot,
                    f"{line.quantite} {line.unite}",
                    format_fcfa(line.prix_unitaire),
                    format_fcfa(line.remise) if line.remise else "",
                    format_fcfa(line.montant_ligne),
                ],
                right=(2, 3, 4, 5),
            )
        fit_columns(lines, 0)
        layout.addWidget(lines, 2)

        totals = f"Brut {format_fcfa(sale.montant_brut)}"
        if sale.remise_globale:
            totals += f"  |  Remise {format_fcfa(sale.remise_globale)}"
        if sale.taux_taxe_bp:
            totals += (
                f"  |  Taxe ({sale.taux_taxe_bp / 100:g} %) "
                f"{format_fcfa(sale.taxes)}"
            )
        totals += (
            f"  |  NET {format_fcfa(sale.montant_net)}"
            f"  |  Payé {format_fcfa(sale.montant_paye)}"
        )
        layout.addWidget(make_label(totals, "sectionTitle"))

        if sale.reste and not sale.is_cancelled:
            layout.addWidget(
                make_label(f"Reste à payer : {format_fcfa(sale.reste)}", "error")
            )

        pays = make_table(
            ["Date", "Référence", "Moyen", "Type", "Montant"],
            stretch_column=2,
        )
        pays.setRowCount(len(details.payments))
        for row, p in enumerate(details.payments):
            refund = p.type == "REMBOURSEMENT"
            fill_row(
                pays,
                row,
                [
                    format_local(p.date_paiement),
                    p.reference,
                    p.method_libelle,
                    "Remboursement" if refund else "Encaissement",
                    ("-" if refund else "") + format_fcfa(p.montant),
                ],
                foreground=ROSE_DARK if refund else None,
                right=(4,),
            )
        fit_columns(pays, 2)
        layout.addWidget(pays, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        back = make_button("Retour aux ventes", "secondary")
        back.clicked.connect(lambda _checked=False: win.show_sales())
        bar.addWidget(back)
        bar.addStretch(1)

        ctx = win.ctx
        if ctx.has(Permission.INVOICES_GENERATE):
            invoice = make_button("Facture PDF", "secondary")
            receipt = make_button("Reçu PDF", "secondary")
            invoice.clicked.connect(lambda _checked=False: self._invoice())
            receipt.clicked.connect(lambda _checked=False: self._receipt())
            bar.addWidget(receipt)
            bar.addWidget(invoice)

        if (
            not sale.is_cancelled
            and sale.reste > 0
            and ctx.has(Permission.PAYMENTS_RECORD)
        ):
            settle = make_button("Encaisser le solde")
            settle.clicked.connect(lambda _checked=False: self._settle())
            bar.addWidget(settle)

        if not sale.is_cancelled and ctx.has(Permission.SALES_CANCEL):
            cancel = make_button("Annuler la vente", "danger")
            cancel.clicked.connect(lambda _checked=False: self._cancel())
            bar.addWidget(cancel)

        layout.addLayout(bar)

    # --- actions -------------------------------------------------------------------

    def _invoice(self) -> None:
        try:
            _invoice, path = self.win.invoices.generate_invoice(
                self.win.ctx, self.sale_id
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        open_pdf(self, path)

    def _receipt(self) -> None:
        try:
            path = self.win.invoices.generate_receipt(self.win.ctx, self.sale_id)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        open_pdf(self, path)

    def _settle(self) -> None:
        sale = self.details.sale
        try:
            methods = self.win.sales.payment_methods(self.win.ctx)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        labels = [m.libelle for m in methods]
        label, ok = QInputDialog.getItem(
            self,
            "Encaisser le solde",
            "Moyen de paiement :",
            labels,
            0,
            False,
        )
        if not ok:
            return

        amount, ok = QInputDialog.getInt(
            self,
            "Encaisser le solde",
            f"Montant remis (reste {format_fcfa(sale.reste)}) :",
            sale.reste,
            1,
            100_000_000,
        )
        if not ok:
            return

        code = methods[labels.index(label)].code
        try:
            result = self.win.sales.record_payment(
                self.win.ctx, self.sale_id, code, amount
            )
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        if result.monnaie:
            QMessageBox.information(
                self,
                "Monnaie à rendre",
                f"Monnaie à rendre : {format_fcfa(result.monnaie)}",
            )
        self.win.show_sale_detail(self.sale_id)

    def _cancel(self) -> None:
        motif, ok = QInputDialog.getText(
            self,
            "Annuler la vente",
            "Motif de l'annulation (le stock sera remis et les paiements remboursés) :",
        )
        if not ok:
            return

        try:
            self.win.sales.cancel_sale(self.win.ctx, self.sale_id, motif)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        self.win.show_sale_detail(self.sale_id)
