"""Facturation : factures numérotées (PDF conservé) et reçus simplifiés."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.core.database import transaction
from app.core.errors import BusinessRuleError, PermissionDeniedError
from app.core.security import Permission, UserContext
from app.core.utils import local_today, now_utc, to_iso
from app.models import Invoice, Sale
from app.repositories import AuditRepository, SaleRepository, SequenceRepository, SettingsRepository
from app.services import pdf

LOGO_FILENAME = "logo.png"


class InvoiceService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        documents_dir: Path,
        clock: Callable[[], datetime] = now_utc,
        logo_path: Path | None = None,
    ) -> None:
        self._conn = conn
        self._dir = documents_dir
        self._clock = clock
        # Filigrane : par défaut `<documents_dir>/logo.png`. Absent ou illisible : pas de filigrane.
        self._logo = logo_path if logo_path is not None else documents_dir / LOGO_FILENAME
        self._sales = SaleRepository(conn)
        self._sequences = SequenceRepository(conn)
        self._settings = SettingsRepository(conn)
        self._audit = AuditRepository(conn)

    def generate_invoice(
        self,
        ctx: UserContext,
        sale_id: int,
        client_nom: str = "",
        client_telephone: str = "",
    ) -> tuple[Invoice, Path]:
        """Émet la facture de la vente (une seule par vente) et (re)génère son PDF."""
        ctx.require(Permission.INVOICES_GENERATE)
        sale = self._sale_for(ctx, sale_id)
        invoice = self._sales.invoice_for_sale(sale_id)

        if invoice is None:
            if sale.is_cancelled:
                raise BusinessRuleError(
                    "Impossible de facturer une vente annulée."
                )

            with transaction(self._conn):
                numero = self._sequences.next_number(
                    "FACTURE", local_today(self._clock).year
                )
                nom = " ".join(client_nom.split()) or sale.client_nom
                phone = client_telephone.strip() or sale.client_telephone

                invoice_id = self._sales.insert_invoice(
                    numero,
                    sale_id,
                    to_iso(self._clock()),
                    ctx.user_id,
                    nom,
                    phone,
                )

                self._audit.add(
                    user_id=ctx.user_id,
                    action="INVOICE_ISSUED",
                    entity_type="invoice",
                    entity_id=invoice_id,
                    details={
                        "numero": numero,
                        "vente": sale.numero_vente,
                    },
                )

            invoice = self._sales.invoice_for_sale(sale_id)

        assert invoice is not None

        path = pdf.build_invoice_pdf(
            self._dir / "factures" / f"{invoice.numero_facture}.pdf",
            pharmacie=self._pharmacie(),
            numero_facture=invoice.numero_facture,
            emise_le=invoice.emise_le,
            sale=sale,
            lines=self._sales.lines(sale_id),
            payments=self._sales.payments(sale_id),
            client_nom=invoice.client_nom,
            client_telephone=invoice.client_telephone,
            taxe_libelle=self._settings.get("taxe_libelle", "TVA"),
            logo_path=self._logo,
        )

        with transaction(self._conn):
            self._sales.set_invoice_pdf(invoice.id, str(path))

        refreshed = self._sales.invoice_for_sale(sale_id)
        assert refreshed is not None

        return refreshed, path

    def generate_receipt(
        self, ctx: UserContext, sale_id: int, monnaie: int = 0
    ) -> Path:
        """Reçu simplifié / preuve de paiement (ticket 80 mm), sans numérotation propre."""
        ctx.require(Permission.INVOICES_GENERATE)
        sale = self._sale_for(ctx, sale_id)

        return pdf.build_receipt_pdf(
            self._dir / "recus" / f"RECU-{sale.numero_vente}.pdf",
            pharmacie=self._pharmacie(),
            sale=sale,
            lines=self._sales.lines(sale_id),
            payments=self._sales.payments(sale_id),
            taxe_libelle=self._settings.get("taxe_libelle", "TVA"),
            monnaie=monnaie,
            logo_path=self._logo,
        )

    # Méthodes internes
    def _sale_for(self, ctx: UserContext, sale_id: int) -> Sale:
        sale = self._sales.get(sale_id)

        if sale is None:
            raise BusinessRuleError("Vente introuvable.")

        if sale.user_id != ctx.user_id and not ctx.has(Permission.SALES_VIEW_ALL):
            raise PermissionDeniedError(
                "Cette vente a été réalisée par un autre utilisateur."
            )

        return sale

    def _pharmacie(self) -> dict[str, str]:
        return {
            "nom": self._settings.get("pharmacie_nom", "Pharmacie"),
            "adresse": self._settings.get("pharmacie_adresse"),
            "telephone": self._settings.get("pharmacie_telephone"),
            "mention": self._settings.get("pharmacie_mention"),
        }