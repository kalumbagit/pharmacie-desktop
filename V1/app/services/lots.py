"""Lots et réceptions de stock.

Règle d'or : aucune quantité n'est modifiée directement. Toute variation passe par un
mouvement de stock ; un trigger SQL met alors à jour `lots.quantite_disponible`, et le
CHECK (>= 0) du lot interdit tout stock négatif.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta

from app.core.database import transaction
from app.core.errors import BusinessRuleError, ValidationError
from app.core.security import Permission, UserContext
from app.core.utils import local_today, now_utc, parse_date
from app.models import Lot, StockMovement,SupplierMovement
from app.repositories import (
    AuditRepository,
    LotRepository,
    MovementRepository,
    ProductRepository,
    SettingsRepository,
    SupplierRepository,
)

DEFAULT_ALERT_DAYS = 90
ENTRY_TYPES = {"STOCK_INITIAL", "ENTREE_APPRO"}


def lot_etat(lot: Lot, today: date, alert_days: int) -> str:
    """OK, PROCHE, EXPIRE, BLOQUE ou EPUISE (voir models.LOT_ETATS)."""
    peremption = date.fromisoformat(lot.date_peremption)
    if peremption < today:
        return "EXPIRE"
    if lot.statut == "BLOQUE":
        return "BLOQUE"
    if lot.quantite_disponible <= 0:
        return "EPUISE"
    if peremption <= today + timedelta(days=alert_days):
        return "PROCHE"
    return "OK"


class LotService:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], datetime] = now_utc) -> None:
        self._conn = conn
        self._clock = clock
        self._lots = LotRepository(conn)
        self._movements = MovementRepository(conn)
        self._products = ProductRepository(conn)
        self._suppliers = SupplierRepository(conn)
        self._settings = SettingsRepository(conn)
        self._audit = AuditRepository(conn)

    # --- lecture -------------------------------------------------------------------
    def alert_days(self) -> int:
        raw = self._settings.get("peremption_alerte_jours", str(DEFAULT_ALERT_DAYS))
        return int(raw) if raw.isdigit() else DEFAULT_ALERT_DAYS

    def _with_etat(self, lots: list[Lot]) -> list[Lot]:
        today = local_today(self._clock)
        days = self.alert_days()
        return [dataclasses.replace(lot, etat=lot_etat(lot, today, days)) for lot in lots]

    def list_lots(
        self,
        ctx: UserContext,
        *,
        search: str = "",
        etat: str | None = None,
        product_id: int | None = None,
        supplier_id: int | None = None,
    ) -> list[Lot]:
        """`etat` : None (tous), OK, PROCHE, EXPIRE, BLOQUE, EPUISE ou VENDABLE (OK + PROCHE)."""
        ctx.require(Permission.LOTS_VIEW)
        lots = self._with_etat(self._lots.list(search, product_id, supplier_id))
        if etat == "VENDABLE":
            return [lot for lot in lots if lot.etat in ("OK", "PROCHE")]
        if etat:
            return [lot for lot in lots if lot.etat == etat]
        return lots

    def get_lot(self, ctx: UserContext, lot_id: int) -> Lot:
        ctx.require(Permission.LOTS_VIEW)
        return self._require(lot_id)

    def movements(self, ctx: UserContext, lot_id: int) -> list[StockMovement]:
        """Conservé : servira à l'historique des livraisons par fournisseur (page produit)."""
        ctx.require(Permission.LOTS_VIEW)
        self._require(lot_id)
        return self._movements.list_for_lot(lot_id)

    def supplier_history(self, ctx: UserContext, supplier_id: int) -> list[SupplierMovement]:
        """Historique complet des transactions liées aux lots d'un fournisseur.

        Couvre : réceptions (STOCK_INITIAL, ENTREE_APPRO), retours fournisseur,
        (seules les livraisons sont listées : STOCK_INITIAL et ENTREE_APPRO).
        """
        ctx.require(Permission.LOTS_VIEW)
        return self._movements.list_for_supplier(supplier_id)

    # --- réception -----------------------------------------------------------------
    def receive_stock(
        self,
        ctx: UserContext,
        *,
        product_id: int,
        supplier_id: int,
        numero_lot: str,
        date_peremption: str,
        quantite: int,
        conditionnement: str = "UNITE",
        prix_achat_total: int = 0,
        date_fabrication: str = "",
        date_reception: str = "",
        motif: str | None = "Stock initial",
    ) -> Lot:
        """Réception manuelle (stock d'ouverture). Les approvisionnements (étape 5)
        utiliseront `receive_internal` après leur propre contrôle de permission."""
        ctx.require(Permission.STOCK_ADJUST)
        return self.receive_internal(
            ctx.user_id,
            product_id=product_id,
            supplier_id=supplier_id,
            numero_lot=numero_lot,
            date_peremption=date_peremption,
            quantite=quantite,
            conditionnement=conditionnement,
            prix_achat_total=prix_achat_total,
            date_fabrication=date_fabrication,
            date_reception=date_reception,
            movement_type="STOCK_INITIAL",
            motif=motif,
        )

    def receive_internal(
        self,
        user_id: int,
        *,
        product_id: int,
        supplier_id: int,
        numero_lot: str,
        date_peremption: str,
        quantite: int,
        conditionnement: str = "UNITE",
        prix_achat_total: int = 0,
        date_fabrication: str = "",
        date_reception: str = "",
        movement_type: str = "ENTREE_APPRO",
        motif: str | None = None,
        ref_type: str | None = None,
        ref_id: int | None = None,
        allow_existing: bool = False,
    ) -> Lot:
        """Crée le lot et enregistre le mouvement d'entrée. AUCUN contrôle de permission :
        à l'appelant.

        Un numéro déjà utilisé pour ce produit est REFUSÉ, sauf `allow_existing=True`
        (réservé à `add_to_lot`) : une faute de frappe ne doit pas fusionner deux lots.

        `prix_achat_total` est le prix payé pour CETTE réception : en cas d'ajout à
        un lot existant, le total du lot est cumulé."""
        if movement_type not in ENTRY_TYPES:
            raise ValidationError("Type de mouvement d'entrée invalide.")
        numero = " ".join(numero_lot.split())
        if not numero or len(numero) > 50:
            raise ValidationError("Le numéro de lot est obligatoire (50 caractères max).")
        if not isinstance(quantite, int) or quantite < 1:
            raise ValidationError("La quantité reçue doit être d'au moins 1.")
        if not isinstance(prix_achat_total, int) or prix_achat_total < 0:
            raise ValidationError("Prix d'achat total invalide.")
        if conditionnement not in ("UNITE", "SOUS_UNITE"):
            raise ValidationError("Conditionnement invalide.")

        today = local_today(self._clock)
        peremption = parse_date(date_peremption, "Date de péremption")
        reception = (
            parse_date(date_reception, "Date de réception")
            if date_reception
            else (today.isoformat())
        )
        fabrication = (
            parse_date(date_fabrication, "Date de fabrication") if date_fabrication else None
        )
        if date.fromisoformat(peremption) <= today:
            raise BusinessRuleError("Ce lot est déjà périmé : il ne peut pas être réceptionné.")
        if date.fromisoformat(reception) > today:
            raise ValidationError("La date de réception ne peut pas être dans le futur.")
        if fabrication is not None and fabrication > reception:
            raise ValidationError("La date de fabrication doit précéder la date de réception.")
        if fabrication is not None and fabrication >= peremption:
            raise ValidationError("La date de fabrication doit précéder la date de péremption.")

        with transaction(self._conn):
            product = self._products.get(product_id)
            if product is None or not product.is_active:
                raise BusinessRuleError("Produit introuvable ou désactivé.")
            supplier = self._suppliers.get(supplier_id)
            if supplier is None or not supplier.is_active:
                raise BusinessRuleError("Fournisseur introuvable ou désactivé.")
            try:
                quantite_base = product.to_base(quantite, conditionnement)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            existing = self._lots.get_by_product_and_number(product_id, numero)
            if existing is None:
                lot_id = self._lots.insert(
                    {
                        "product_id": product_id,
                        "supplier_id": supplier_id,
                        "numero_lot": numero,
                        "date_fabrication": fabrication,
                        "date_peremption": peremption,
                        "date_reception": reception,
                        "quantite_recue": quantite_base,
                        "quantite_disponible": 0,  # mis à jour par le mouvement ci-dessous
                        "prix_achat_total": prix_achat_total,
                    },
                    user_id,
                )
            else:
                if not allow_existing:
                    raise BusinessRuleError(
                        "Ce numéro de lot existe déjà pour ce produit. Pour y ajouter du stock, "
                        "sélectionnez le lot dans la liste puis cliquez sur « Ajouter au lot »."
                    )
                if existing.supplier_id != supplier_id or existing.date_peremption != peremption:
                    raise BusinessRuleError(
                        "Ce numéro de lot existe déjà pour ce produit avec un autre fournisseur "
                        "ou une autre date de péremption."
                    )
                if (
                    fabrication is not None
                    and existing.date_fabrication is not None
                    and existing.date_fabrication != fabrication
                ):
                    raise BusinessRuleError(
                        "Ce lot existe déjà avec une autre date de fabrication."
                    )
                if existing.statut == "BLOQUE":
                    raise BusinessRuleError("Ce lot est bloqué : déblocage requis avant réception.")
                lot_id = existing.id
                # Cumul : quantité ET prix d'achat total s'ajoutent.
                self._lots.add_received(lot_id, quantite_base, prix_achat_total)

            self._movements.insert(
                type=movement_type,
                product_id=product_id,
                lot_id=lot_id,
                quantite_signee=quantite_base,
                user_id=user_id,
                motif=motif,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            self._audit.add(
                user_id=user_id,
                action="LOT_RECEIVED",
                entity_type="lot",
                entity_id=lot_id,
                details={
                    "produit": product.code,
                    "numero_lot": numero,
                    "quantite_base": quantite_base,
                    "prix_achat_total": prix_achat_total,
                    "nouveau_lot": existing is None,
                },
            )
            lot = self._require(lot_id)
        return lot

    # --- ajout à un lot existant -----------------------------------------------------
    def add_to_lot(
        self,
        ctx: UserContext,
        lot_id: int,
        *,
        quantite: int,
        conditionnement: str = "UNITE",
        prix_achat_total: int = 0,
        motif: str | None = None,
    ) -> Lot:
        """Nouvelle livraison d'un lot déjà connu : produit, fournisseur, numéro et dates
        sont ceux du lot (non modifiables ici) ; seuls la quantité et le coût de CETTE
        livraison sont saisis. Enregistré comme entrée d'approvisionnement."""
        ctx.require(Permission.STOCK_ADJUST)
        lot = self._require(lot_id)
        return self.receive_internal(
            ctx.user_id,
            product_id=lot.product_id,
            supplier_id=lot.supplier_id,
            numero_lot=lot.numero_lot,
            date_peremption=lot.date_peremption,
            date_fabrication=lot.date_fabrication or "",
            quantite=quantite,
            conditionnement=conditionnement,
            prix_achat_total=prix_achat_total,
            movement_type="ENTREE_APPRO",
            motif=motif or "Livraison complémentaire du lot",
            allow_existing=True,
        )

    # --- correction d'un lot ---------------------------------------------------------
    def update_lot(
        self,
        ctx: UserContext,
        lot_id: int,
        *,
        numero_lot: str,
        supplier_id: int,
        date_peremption: str,
        date_reception: str,
        prix_achat_total: int,
        date_fabrication: str = "",
        motif: str = "",
    ) -> Lot:
        """Corrige les informations d'un lot (erreur de saisie). Le produit et la quantité
        ne changent jamais ici : la quantité ne varie que par mouvement de stock.
        Un motif est exigé dès que le lot a déjà servi (vente, retour, ajustement...)."""
        ctx.require(Permission.STOCK_ADJUST)
        numero = " ".join(numero_lot.split())
        if not numero or len(numero) > 50:
            raise ValidationError("Le numéro de lot est obligatoire (50 caractères max).")
        if not isinstance(prix_achat_total, int) or prix_achat_total < 0:
            raise ValidationError("Prix d'achat total invalide.")
        today = local_today(self._clock)
        peremption = parse_date(date_peremption, "Date de péremption")
        reception = parse_date(date_reception, "Date de réception")
        fabrication = (
            parse_date(date_fabrication, "Date de fabrication") if date_fabrication else None
        )
        if date.fromisoformat(reception) > today:
            raise ValidationError("La date de réception ne peut pas être dans le futur.")
        if fabrication is not None and fabrication > reception:
            raise ValidationError("La date de fabrication doit précéder la date de réception.")
        if fabrication is not None and fabrication >= peremption:
            raise ValidationError("La date de fabrication doit précéder la date de péremption.")
        reason = " ".join(motif.split())

        with transaction(self._conn):
            lot = self._require(lot_id)
            supplier = self._suppliers.get(supplier_id)
            if supplier is None or (not supplier.is_active and supplier_id != lot.supplier_id):
                raise BusinessRuleError("Fournisseur introuvable ou désactivé.")
            other = self._lots.get_by_product_and_number(lot.product_id, numero)
            if other is not None and other.id != lot_id:
                raise BusinessRuleError("Un autre lot de ce produit porte déjà ce numéro.")

            new_values = {
                "numero_lot": numero,
                "supplier_id": supplier_id,
                "date_fabrication": fabrication,
                "date_peremption": peremption,
                "date_reception": reception,
                "prix_achat_total": prix_achat_total,
            }
            changes = {
                key: {"avant": getattr(lot, key), "apres": value}
                for key, value in new_values.items()
                if getattr(lot, key) != value
            }
            if not changes:
                raise ValidationError("Aucune modification à enregistrer.")
            if self._lots.has_exit_history(lot_id) and not reason:
                raise ValidationError(
                    "Le motif est obligatoire : ce lot a déjà fait l'objet de ventes ou "
                    "d'autres mouvements."
                )
            self._lots.update(lot_id, new_values)
            self._audit.add(
                user_id=ctx.user_id,
                action="LOT_UPDATED",
                entity_type="lot",
                entity_id=lot_id,
                details={"numero_lot": lot.numero_lot, "modifications": changes,
                         "motif": reason or None},
            )
            updated = self._require(lot_id)
        return updated

    # --- blocage -------------------------------------------------------------------
    def set_blocked(self, ctx: UserContext, lot_id: int, blocked: bool, motif: str = "") -> Lot:
        """Un lot bloqué n'est plus proposé à la vente (qualité, rappel, litige...)."""
        ctx.require(Permission.STOCK_ADJUST)
        reason = " ".join(motif.split())
        if blocked and not reason:
            raise ValidationError("Le motif du blocage est obligatoire.")
        with transaction(self._conn):
            lot = self._require(lot_id)
            self._lots.set_status(lot_id, "BLOQUE" if blocked else "ACTIF")
            self._audit.add(
                user_id=ctx.user_id,
                action="LOT_BLOCKED" if blocked else "LOT_UNBLOCKED",
                entity_type="lot",
                entity_id=lot_id,
                details={"numero_lot": lot.numero_lot, "motif": reason or None},
            )
            updated = self._require(lot_id)
        return updated

    # --- interne -------------------------------------------------------------------
    def _require(self, lot_id: int) -> Lot:
        lot = self._lots.get(lot_id)
        if lot is None:
            raise BusinessRuleError("Lot introuvable.")
        return self._with_etat([lot])[0]