"""Produits pharmaceutiques (avec gestion des sous-unités)."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.core.database import transaction
from app.core.errors import BusinessRuleError, ValidationError
from app.core.security import Permission, UserContext
from app.models import Product
from app.repositories import AuditRepository, ProductRepository, ReferenceRepository
from app.core.enums import Forme, UniteVente,SousUnite   # ← nouveau

MAX_AMOUNT = 100_000_000
_BARCODE = re.compile(r"^[0-9A-Za-z-]{4,32}$")

PRODUCT_CODE_PREFIX = "MED"
PRODUCT_CODE_WIDTH = 6
PRODUCT_CODE_START = 1


@dataclass(frozen=True)
class ProductInput:
    nom_commercial: str
    unite_vente: UniteVente = UniteVente.BOITE      # ← était str = "Boîte"
    code_barres: str = ""
    description: str = ""
    categorie: str = ""
    code: str | None = None
    forme: Forme | None = None                       # ← était str = ""
    dosage: str = ""
    sous_unite: str = ""
    sous_unites_par_unite: int = 1
    prix_vente: int = 0
    prix_vente_sous_unite: int = 0
    seuil_minimal: int = 0  # en unité de base



def _text(value: str, label: str, max_len: int, required: bool = False) -> str | None:
    cleaned = " ".join(value.split())
    if not cleaned:
        if required:
            raise ValidationError(f"Le champ « {label} » est obligatoire.")
        return None
    if len(cleaned) > max_len:
        raise ValidationError(f"Le champ « {label} » est trop long ({max_len} caractères max).")
    return cleaned


def _amount(value: int, label: str) -> int:
    if not isinstance(value, int) or value < 0 or value > MAX_AMOUNT:
        raise ValidationError(f"{label} : montant invalide.")
    return value


def _clean(data: ProductInput) -> dict[str, Any]:
    """Valide et normalise la saisie. Retourne les valeurs prêtes pour la base."""

    barcode = data.code_barres.strip() or None
    forme_value = data.forme.value if data.forme else None

    if barcode is not None and not _BARCODE.match(barcode):
        raise ValidationError("Le code-barres doit contenir de 4 à 32 caractères alphanumériques.")

    sous_unite = _text(data.sous_unite, "Sous-unité", 40)
    if sous_unite:
        if data.sous_unites_par_unite < 2:
            raise ValidationError("Une sous-unité exige au moins 2 sous-unités par unité de vente.")
        par_unite = data.sous_unites_par_unite
        prix_sous_unite: int | None = _amount(data.prix_vente_sous_unite, "Prix de la sous-unité")
    else:
        par_unite = 1
        prix_sous_unite = None

    return {
        "code_barres": barcode,
        "code": data.code or None,
        "nom_commercial": _text(data.nom_commercial, "Nom commercial", 150, required=True),
        "description": _text(data.description, "Description", 300),
        "dosage": _text(data.dosage, "Dosage", 60),
        "sous_unite": sous_unite,
        "sous_unites_par_unite": par_unite,
        "prix_vente": _amount(data.prix_vente, "Prix de vente"),
        "prix_vente_sous_unite": prix_sous_unite,
        "seuil_minimal": _amount(data.seuil_minimal, "Seuil minimal"),
        "unite_vente": data.unite_vente.value,           # ← plus de _text
        "forme": forme_value, 
    }


class ProductService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._products = ProductRepository(conn)
        self._categories = ReferenceRepository(conn, "categories")
        self._audit = AuditRepository(conn)

    # --- lecture -------------------------------------------------------------------
    def list_products(
        self, ctx: UserContext, search: str = "", statut: str | None = None
    ) -> list[Product]:
        ctx.require(Permission.PRODUCTS_VIEW)
        return self._products.list(search, statut)

    def get_product(self, ctx: UserContext, product_id: int) -> Product:
        ctx.require(Permission.PRODUCTS_VIEW)
        return self._require(product_id)

    def find_by_barcode(self, ctx: UserContext, barcode: str) -> Product | None:
        ctx.require(Permission.PRODUCTS_VIEW)
        return self._products.get_by_barcode(barcode.strip())

    def list_categories(self, ctx: UserContext) -> list[str]:
        ctx.require(Permission.PRODUCTS_VIEW)
        return self._categories.names()
    
    def list_formes(self, ctx: UserContext) -> list[str]:
        ctx.require(Permission.PRODUCTS_VIEW)
        return list(Forme.values())

    def list_unites(self, ctx: UserContext) -> list[str]:
        ctx.require(Permission.PRODUCTS_VIEW)
        return list(UniteVente.values())

    def list_sous_unites(self, ctx: UserContext) -> list[str]:
        ctx.require(Permission.PRODUCTS_VIEW)
        return list(SousUnite.values())
    
    def has_lots(self, ctx: UserContext, product_id: int) -> bool:
        ctx.require(Permission.PRODUCTS_VIEW)
        return self._products.has_lots(product_id)

    # --- écriture ------------------------------------------------------------------
    def create_product(self, ctx: UserContext, data: ProductInput) -> Product:
        ctx.require(Permission.PRODUCTS_EDIT)
        values = _clean(data)
        if values["prix_vente"] or values["prix_vente_sous_unite"]:
            ctx.require(Permission.PRICE_EDIT)

        with transaction(self._conn):
            values["code"] = self._generate_product_code()
            values.update(self._reference_ids(data))
            product_id = self._products.insert(values, ctx.user_id)
            self._audit.add(
                user_id=ctx.user_id,
                action="PRODUCT_CREATED",
                entity_type="product",
                entity_id=product_id,
                details={"code": values["code"], "prix_vente": values["prix_vente"]},
            )
            product = self._products.get(product_id)
        assert product is not None
        return product

    def update_product(self, ctx: UserContext, product_id: int, data: ProductInput) -> Product:
        ctx.require(Permission.PRODUCTS_EDIT)
        values = _clean(data)

        with transaction(self._conn):
            old = self._require(product_id)
            price_changed = (
                values["prix_vente"] != old.prix_vente
                or values["prix_vente_sous_unite"] != old.prix_vente_sous_unite
            )
            if price_changed:
                ctx.require(Permission.PRICE_EDIT)

            packaging_changed = (
                values["sous_unite"] != old.sous_unite
                or values["sous_unites_par_unite"] != old.sous_unites_par_unite
            )
            if packaging_changed and self._products.has_lots(product_id):
                raise BusinessRuleError(
                    "Le conditionnement (sous-unité) ne peut plus changer : "
                    "ce produit possède déjà des lots."
                )

            values.update(self._reference_ids(data))
            self._products.update(product_id, values)

            details: dict[str, Any] = {"code": values["code"]}
            if price_changed:
                details["prix_vente"] = [old.prix_vente, values["prix_vente"]]
                details["prix_vente_sous_unite"] = [
                    old.prix_vente_sous_unite,
                    values["prix_vente_sous_unite"],
                ]
            self._audit.add(
                user_id=ctx.user_id,
                action="PRODUCT_UPDATED",
                entity_type="product",
                entity_id=product_id,
                details=details,
            )
            product = self._products.get(product_id)
        assert product is not None
        return product

    def set_active(self, ctx: UserContext, product_id: int, active: bool) -> Product:
        ctx.require(Permission.PRODUCTS_EDIT)
        with transaction(self._conn):
            self._require(product_id)
            self._products.set_status(product_id, "ACTIF" if active else "INACTIF")
            self._audit.add(
                user_id=ctx.user_id,
                action="PRODUCT_REACTIVATED" if active else "PRODUCT_DEACTIVATED",
                entity_type="product",
                entity_id=product_id,
            )
            product = self._products.get(product_id)
        assert product is not None
        return product

    # --- interne -------------------------------------------------------------------
    def _require(self, product_id: int) -> Product:
        product = self._products.get(product_id)
        if product is None:
            raise BusinessRuleError("Produit introuvable.")
        return product

    def _check_unique(self, code: str, barcode: str | None, own_id: int | None) -> None:
        existing = self._products.get_by_code(code)
        if existing is not None and existing.id != own_id:
            raise BusinessRuleError(f"Le code produit « {code} » existe déjà.")
        if barcode is not None:
            other = self._products.get_by_barcode(barcode)
            if other is not None and other.id != own_id:
                raise BusinessRuleError(
                    f"Ce code-barres est déjà utilisé par le produit « {other.nom_commercial} »."
                )

    def _reference_ids(self, data: ProductInput) -> dict[str, int | None]:
        categorie = _text(data.categorie, "Catégorie", 60)
        return {
            "categorie_id": self._categories.get_or_create(categorie) if categorie else None,
        }

    def _generate_product_code(self) -> str:
        last_code = self._products.get_last_code(
            PRODUCT_CODE_PREFIX,
            PRODUCT_CODE_WIDTH,
        )

        if last_code is None:
            next_number = PRODUCT_CODE_START
        else:
            next_number = int(last_code.split("-")[-1]) + 1

        return f"{PRODUCT_CODE_PREFIX}-{next_number:0{PRODUCT_CODE_WIDTH}d}"