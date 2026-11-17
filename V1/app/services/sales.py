"""Ventes : panier, répartition FEFO sur les lots, paiements, annulation.

Une vente est validée en UNE transaction (BEGIN IMMEDIATE) : contrôle du stock,
répartition FEFO, lignes, mouvements de stock, paiements, numérotation et audit. Un jeton
d'idempotence (créé avec le panier) rend la double validation inoffensive.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.database import transaction
from app.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from app.core.security import Permission, UserContext
from app.core.utils import local_day_bounds, local_today, now_utc, to_iso
from app.models import Lot, Payment, PaymentMethod, Product, Sale, SaleLine
from app.repositories import (
    AuditRepository,
    LotRepository,
    MovementRepository,
    ProductRepository,
    SettingsRepository,
     CashRepository,
    PaymentMethodRepository,
    SaleRepository,
    SequenceRepository,
    StatsRepository,
)


MAX_AMOUNT = 100_000_000
_PHONE = re.compile(r"^[0-9+() .-]{6,20}$")


@dataclass(frozen=True)
class CartItem:
    product_id: int
    quantite: int
    conditionnement: str = "UNITE"
    remise: int = 0
    prix_unitaire: int | None = None


@dataclass(frozen=True)
class PaymentInput:
    method_code: str
    montant: int
    note: str = ""


@dataclass(frozen=True)
class QuoteLine:
    product: Product
    conditionnement: str
    quantite: int
    prix_unitaire: int
    remise: int
    total: int


@dataclass(frozen=True)
class Quote:
    lignes: list[QuoteLine]
    brut: int
    remise_globale: int
    taux_taxe_bp: int
    taxes: int
    net: int


@dataclass(frozen=True)
class SellableProduct:
    product: Product
    stock_base: int


@dataclass(frozen=True)
class SaleDetails:
    sale: Sale
    lines: list[SaleLine]
    payments: list[Payment]


@dataclass(frozen=True)
class SaleResult:
    sale: Sale
    lines: list[SaleLine]
    payments: list[Payment]
    monnaie: int = 0
    deja_traitee: bool = False
    notes: list[str] = field(default_factory=list)


def compute_tax(taxable: int, taux_bp: int) -> int:
    """Taxe arrondie à l'entier le plus proche (0,5 vers le haut)."""
    return (taxable * taux_bp + 5000) // 10000


class SaleService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Callable[[], datetime] = now_utc
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._products = ProductRepository(conn)
        self._lots = LotRepository(conn)
        self._movements = MovementRepository(conn)
        self._settings = SettingsRepository(conn)
        self._audit = AuditRepository(conn)
        self._cash = CashRepository(conn)
        self._methods = PaymentMethodRepository(conn)
        self._sales = SaleRepository(conn)
        self._sequences = SequenceRepository(conn)
        self._stats = StatsRepository(conn)

    # Recherche produit pour la caisse
    def search_products(
        self,
        ctx: UserContext,
        text: str = "",
        limit: int = 60,
        include_out_of_stock: bool = False,
    ) -> list[SellableProduct]:
        """Produits proposés à la caisse. Par défaut, seuls ceux qui ont du stock vendable
        (lot actif, non périmé, en stock) sont listés ; le filtre est appliqué AVANT la
        limite pour que les ruptures ne masquent pas les produits vendables."""
        ctx.require(Permission.SALES_CREATE)
        ctx.require(Permission.PRODUCTS_VIEW)
        products = self._products.list(text, "ACTIF")
        stock = self._stats.stock_for_products(
            [p.id for p in products], local_today(self._clock).isoformat()
        )
        items = [SellableProduct(p, stock.get(p.id, 0)) for p in products]
        if not include_out_of_stock:
            items = [item for item in items if item.stock_base > 0]
        return items[:limit]

    def find_exact(self, ctx: UserContext, text: str) -> Product | None:
        """Code-barres ou code produit exact (scan) ; produit actif uniquement."""
        ctx.require(Permission.SALES_CREATE)
        ctx.require(Permission.PRODUCTS_VIEW)
        value = text.strip()
        if not value:
            return None
        product = self._products.get_by_barcode(value) or self._products.get_by_code(value)
        return product if product is not None and product.is_active else None

    def payment_methods(self, ctx: UserContext) -> list[PaymentMethod]:
        ctx.require(Permission.PAYMENTS_RECORD)
        return self._methods.list_active()

    # Devis
    def quote(
        self, ctx: UserContext, items: list[CartItem], remise_globale: int = 0
    ) -> Quote:
        ctx.require(Permission.SALES_CREATE)
        return self._quote(ctx, items, remise_globale)

    def _quote(self, ctx: UserContext, items: list[CartItem], remise_globale: int) -> Quote:
        if not isinstance(remise_globale, int) or remise_globale < 0:
            raise ValidationError("Remise globale invalide.")

        lignes: list[QuoteLine] = []
        gross_before_discount = 0
        total_discount = remise_globale

        for item in items:
            line = self._price_item(ctx, item)
            lignes.append(line)
            gross_before_discount += line.quantite * line.prix_unitaire
            total_discount += line.remise

        brut = sum(line.total for line in lignes)

        if remise_globale > brut:
            raise ValidationError("La remise globale dépasse le montant de la vente.")

        if total_discount > 0:
            ctx.require(Permission.SALES_DISCOUNT)
            max_pct = self._max_discount_pct(ctx.role_code)
            if total_discount * 100 > max_pct * gross_before_discount:
                raise BusinessRuleError(
                    f"Remise maximale autorisée pour votre profil : {max_pct} %."
                )

        taux = self._tax_rate_bp()
        taxable = brut - remise_globale
        taxes = compute_tax(taxable, taux)

        return Quote(lignes, brut, remise_globale, taux, taxes, taxable + taxes)

    def _price_item(self, ctx: UserContext, item: CartItem) -> QuoteLine:
        if not isinstance(item.quantite, int) or item.quantite < 1:
            raise ValidationError("La quantité doit être d'au moins 1.")

        if not isinstance(item.remise, int) or item.remise < 0:
            raise ValidationError("Remise de ligne invalide.")

        if item.conditionnement not in ("UNITE", "SOUS_UNITE"):
            raise ValidationError("Conditionnement invalide.")

        product = self._products.get(item.product_id)

        if product is None or not product.is_active:
            raise BusinessRuleError("Produit introuvable ou désactivé.")

        if item.conditionnement == "SOUS_UNITE":
            if not product.has_sous_unite:
                raise ValidationError(f"« {product.nom_commercial} » n'a pas de sous-unité.")
            catalogue = product.prix_vente_sous_unite or 0
        else:
            catalogue = product.prix_vente

        if item.prix_unitaire is None:
            prix = catalogue
        else:
            if item.prix_unitaire != catalogue:
                ctx.require(Permission.PRICE_EDIT)
            prix = item.prix_unitaire

        if not isinstance(prix, int) or prix <= 0 or prix > MAX_AMOUNT:
            raise BusinessRuleError(
                f"« {product.nom_commercial} » n'a pas de prix de vente valide."
            )

        brut_ligne = item.quantite * prix

        if item.remise > brut_ligne:
            raise ValidationError("La remise d'une ligne dépasse son montant.")

        return QuoteLine(
            product,
            item.conditionnement,
            item.quantite,
            prix,
            item.remise,
            brut_ligne - item.remise,
        )

    # Validation d'une vente
    def validate_sale(
        self,
        ctx: UserContext,
        *,
        token: str,
        items: list[CartItem],
        payments: list[PaymentInput],
        remise_globale: int = 0,
        client_nom: str = "",
        client_telephone: str = "",
    ) -> SaleResult:
        ctx.require(Permission.SALES_CREATE)

        if payments:
            ctx.require(Permission.PAYMENTS_RECORD)

        token = token.strip()

        if not token or len(token) > 64:
            raise ValidationError("Jeton de vente invalide.")

        if not items:
            raise ValidationError("Le panier est vide.")

        nom = " ".join(client_nom.split()) or None
        phone = client_telephone.strip() or None

        if nom is not None and len(nom) > 120:
            raise ValidationError("Le nom du client est trop long.")

        if phone is not None and not _PHONE.match(phone):
            raise ValidationError("Numéro de téléphone du client invalide.")

        with transaction(self._conn):
            existing = self._sales.get_by_token(token)

            if existing is not None:
                return SaleResult(
                    existing,
                    self._sales.lines(existing.id),
                    self._sales.payments(existing.id),
                    deja_traitee=True,
                )

            session = self._cash.get_open(ctx.user_id)

            if session is None:
                raise BusinessRuleError(
                    "Ouvrez d'abord votre caisse pour enregistrer une vente."
                )

            quote = self._quote(ctx, items, remise_globale)
            applied, monnaie = self._apply_payments(quote.net, payments)
            paye = sum(amount for _, amount, _ in applied)

            if paye < quote.net and nom is None:
                raise BusinessRuleError(
                    "Paiement insuffisant : indiquez le nom du client pour une vente à crédit."
                )

            now = self._clock()
            today = local_today(self._clock)

            sale_id = self._sales.insert_sale(
                {
                    "numero_vente": self._sequences.next_number("VENTE", today.year),
                    "token_idempotence": token,
                    "date_vente": to_iso(now),
                    "user_id": ctx.user_id,
                    "cash_session_id": session.id,
                    "client_nom": nom,
                    "client_telephone": phone,
                    "montant_brut": quote.brut,
                    "remise_globale": quote.remise_globale,
                    "taux_taxe_bp": quote.taux_taxe_bp,
                    "taxes": quote.taxes,
                    "montant_net": quote.net,
                }
            )

            nb_lignes = 0

            for line in quote.lignes:
                nb_lignes += self._sell_line(ctx, sale_id, line, today)

            self._record_payments(
                ctx, sale_id, session.id, applied, to_iso(now), today.year, "ENCAISSEMENT"
            )

            self._audit.add(
                user_id=ctx.user_id,
                action="SALE_VALIDATED",
                entity_type="sale",
                entity_id=sale_id,
                details={"net": quote.net, "lignes": nb_lignes, "paye": paye},
            )

            sale = self._sales.get(sale_id)

        assert sale is not None

        return SaleResult(
            sale,
            self._sales.lines(sale_id),
            self._sales.payments(sale_id),
            monnaie=monnaie,
        )

    # Répartition FEFO
    def _sell_line(
        self, ctx: UserContext, sale_id: int, line: QuoteLine, today: date
    ) -> int:
        """Prélève la ligne du panier sur les lots (FEFO)."""
        plan = self._allocate(line.product, line.conditionnement, line.quantite, today)
        gross_total = line.quantite * line.prix_unitaire
        remaining_discount = line.remise

        for index, (lot, quantite, quantite_base) in enumerate(plan):
            gross = quantite * line.prix_unitaire

            if index == len(plan) - 1:
                remise = remaining_discount
            else:
                remise = line.remise * gross // gross_total

            remaining_discount -= remise

            cout = (
                lot.prix_achat_total * quantite_base + lot.quantite_recue // 2
            ) // lot.quantite_recue

            self._sales.insert_line(
                {
                    "sale_id": sale_id,
                    "product_id": line.product.id,
                    "lot_id": lot.id,
                    "conditionnement": line.conditionnement,
                    "quantite": quantite,
                    "quantite_base": quantite_base,
                    "prix_unitaire": line.prix_unitaire,
                    "cout_total": cout,
                    "remise": remise,
                    "montant_ligne": gross - remise,
                }
            )

            self._movements.insert(
                type="VENTE",
                product_id=line.product.id,
                lot_id=lot.id,
                quantite_signee=-quantite_base,
                user_id=ctx.user_id,
                ref_type="sale",
                ref_id=sale_id,
            )

        return len(plan)

    def _allocate(
        self, product: Product, conditionnement: str, quantite: int, today: date
    ) -> list[tuple[Lot, int, int]]:
        """FEFO : prélèvement des lots selon la date de péremption."""
        size = product.sous_unites_par_unite if conditionnement == "UNITE" else 1
        sellable = self._lots.list_sellable(product.id, today.isoformat())

        remaining = quantite
        plan: list[tuple[Lot, int, int]] = []

        for lot in sellable:
            take = min(remaining, lot.quantite_disponible // size)

            if take > 0:
                plan.append((lot, take, take * size))
                remaining -= take

            if remaining == 0:
                break

        if remaining > 0:
            disponible = sum(lot.quantite_disponible for lot in sellable)
            unite = (
                product.sous_unite
                if conditionnement == "SOUS_UNITE"
                else product.unite_vente
            )
            raise BusinessRuleError(
                f"Stock insuffisant pour « {product.nom_commercial} » : "
                f"{quantite} {unite} demandé(s), "
                f"{product.format_quantity(disponible)} vendable(s)."
            )

        return plan

    # Paiements
    def _apply_payments(
        self, due: int, inputs: list[PaymentInput]
    ) -> tuple[list[tuple[PaymentMethod, int, str | None]], int]:
        remaining = due
        applied: list[tuple[PaymentMethod, int, str | None]] = []
        monnaie = 0

        for payment in inputs:
            method = self._methods.get_by_code(payment.method_code)

            if method is None:
                raise ValidationError(
                    f"Moyen de paiement inconnu : {payment.method_code}."
                )

            if not isinstance(payment.montant, int) or not 0 < payment.montant <= MAX_AMOUNT:
                raise ValidationError("Montant de paiement invalide.")

            if method.is_cash:
                amount = min(payment.montant, remaining)
                monnaie += payment.montant - amount
            else:
                if payment.montant > remaining:
                    raise ValidationError(
                        f"Le paiement « {method.libelle} » dépasse "
                        f"le montant restant ({remaining})."
                    )
                amount = payment.montant

            if amount > 0:
                applied.append((method, amount, payment.note.strip() or None))
                remaining -= amount

        return applied, monnaie

    def _record_payments(
        self,
        ctx: UserContext,
        sale_id: int,
        session_id: int,
        applied: list[tuple[PaymentMethod, int, str | None]],
        when: str,
        year: int,
        kind: str,
    ) -> None:
        for method, amount, note in applied:
            self._sales.insert_payment(
                {
                    "reference": self._sequences.next_number("PAIEMENT", year),
                    "sale_id": sale_id,
                    "payment_method_id": method.id,
                    "cash_session_id": session_id,
                    "type": kind,
                    "montant": amount,
                    "date_paiement": when,
                    "user_id": ctx.user_id,
                    "note": note,
                }
            )

    def record_payment(
        self, ctx: UserContext, sale_id: int, method_code: str, montant: int, note: str = ""
    ) -> SaleResult:
        """Encaisse tout ou partie du solde d'une vente à crédit."""
        ctx.require(Permission.PAYMENTS_RECORD)

        with transaction(self._conn):
            sale = self._require(sale_id)
            self._check_access(ctx, sale)

            if sale.is_cancelled:
                raise BusinessRuleError("Cette vente est annulée.")

            if sale.reste <= 0:
                raise BusinessRuleError("Cette vente est déjà soldée.")

            session = self._cash.get_open(ctx.user_id)

            if session is None:
                raise BusinessRuleError(
                    "Ouvrez votre caisse pour enregistrer un encaissement."
                )

            applied, monnaie = self._apply_payments(
                sale.reste, [PaymentInput(method_code, montant, note)]
            )

            now = self._clock()

            self._record_payments(
                ctx,
                sale_id,
                session.id,
                applied,
                to_iso(now),
                local_today(self._clock).year,
                "ENCAISSEMENT",
            )

            self._audit.add(
                user_id=ctx.user_id,
                action="PAYMENT_RECORDED",
                entity_type="sale",
                entity_id=sale_id,
                details={
                    "montant": sum(a for _, a, _ in applied),
                    "moyen": method_code,
                },
            )

            updated = self._require(sale_id)

        return SaleResult(
            updated,
            self._sales.lines(sale_id),
            self._sales.payments(sale_id),
            monnaie=monnaie,
        )

    # Annulation
    def cancel_sale(self, ctx: UserContext, sale_id: int, motif: str) -> Sale:
        """Annule une vente sans supprimer son historique."""
        ctx.require(Permission.SALES_CANCEL)
        reason = " ".join(motif.split())

        if not reason:
            raise ValidationError("Le motif d'annulation est obligatoire.")

        with transaction(self._conn):
            sale = self._require(sale_id)

            if sale.is_cancelled:
                raise BusinessRuleError("Cette vente est déjà annulée.")

            refunds = self._sales.net_paid_by_method(sale_id)
            session = self._cash.get_open(ctx.user_id)

            if refunds and session is None:
                raise BusinessRuleError(
                    "Ouvrez votre caisse pour rembourser cette vente."
                )

            for line in self._sales.lines(sale_id):
                self._movements.insert(
                    type="ANNULATION_VENTE",
                    product_id=line.product_id,
                    lot_id=line.lot_id,
                    quantite_signee=line.quantite_base,
                    user_id=ctx.user_id,
                    motif=reason,
                    ref_type="sale",
                    ref_id=sale_id,
                )

            now = to_iso(self._clock())

            if refunds and session is not None:
                for method_id, amount in refunds:
                    self._sales.insert_payment(
                        {
                            "reference": self._sequences.next_number(
                                "PAIEMENT", local_today(self._clock).year
                            ),
                            "sale_id": sale_id,
                            "payment_method_id": method_id,
                            "cash_session_id": session.id,
                            "type": "REMBOURSEMENT",
                            "montant": amount,
                            "date_paiement": now,
                            "user_id": ctx.user_id,
                            "note": f"Annulation {sale.numero_vente}",
                        }
                    )

            self._sales.mark_cancelled(sale_id, now, ctx.user_id, reason)

            self._audit.add(
                user_id=ctx.user_id,
                action="SALE_CANCELLED",
                entity_type="sale",
                entity_id=sale_id,
                details={"numero": sale.numero_vente, "motif": reason},
            )

            cancelled = self._require(sale_id)

        return cancelled

    # Consultation
    def list_sales(self, ctx: UserContext, day: date | None = None) -> list[Sale]:
        """Ventes d'une journée locale."""
        ctx.require(Permission.SALES_VIEW_OWN)
        start, end = local_day_bounds(day or local_today(self._clock))
        user_id = None if ctx.has(Permission.SALES_VIEW_ALL) else ctx.user_id
        return self._sales.list(start, end, user_id)

    def get_details(self, ctx: UserContext, sale_id: int) -> SaleDetails:
        ctx.require(Permission.SALES_VIEW_OWN)
        sale = self._require(sale_id)
        self._check_access(ctx, sale)
        return SaleDetails(
            sale,
            self._sales.lines(sale_id),
            self._sales.payments(sale_id),
        )

    # Méthodes internes
    def _require(self, sale_id: int) -> Sale:
        sale = self._sales.get(sale_id)

        if sale is None:
            raise BusinessRuleError("Vente introuvable.")

        return sale

    @staticmethod
    def _check_access(ctx: UserContext, sale: Sale) -> None:
        if sale.user_id != ctx.user_id and not ctx.has(Permission.SALES_VIEW_ALL):
            raise PermissionDeniedError(
                "Cette vente a été réalisée par un autre utilisateur."
            )

    def _tax_rate_bp(self) -> int:
        raw = self._settings.get("taxe_vente_bp", "0")
        return int(raw) if raw.isdigit() else 0

    def _max_discount_pct(self, role_code: str) -> int:
        raw = self._settings.get(f"remise_max_pct_{role_code}", "0")
        return int(raw) if raw.isdigit() else 0
