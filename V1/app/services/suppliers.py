"""Fournisseurs."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from app.core.database import transaction
from app.core.errors import BusinessRuleError, ValidationError
from app.core.security import Permission, UserContext
from app.models import Supplier
from app.repositories import AuditRepository, SupplierRepository

_PHONE = re.compile(r"^[0-9+() .-]{6,20}$")


@dataclass(frozen=True)
class SupplierInput:
    nom: str
    telephone: str = ""
    adresse: str = ""


def _clean(data: SupplierInput) -> tuple[str, str | None, str | None]:
    nom = " ".join(data.nom.split())
    if not nom:
        raise ValidationError("Le nom du fournisseur est obligatoire.")
    if len(nom) > 120:
        raise ValidationError("Le nom du fournisseur est trop long (120 caractères max).")
    telephone = data.telephone.strip() or None
    if telephone is not None and not _PHONE.match(telephone):
        raise ValidationError("Numéro de téléphone invalide.")
    adresse = " ".join(data.adresse.split()) or None
    if adresse is not None and len(adresse) > 200:
        raise ValidationError("L'adresse est trop longue (200 caractères max).")
    return nom, telephone, adresse


class SupplierService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._suppliers = SupplierRepository(conn)
        self._audit = AuditRepository(conn)

    def list_suppliers(
        self, ctx: UserContext, search: str = "", statut: str | None = None
    ) -> list[Supplier]:
        ctx.require(Permission.SUPPLIERS_VIEW)
        return self._suppliers.list(search, statut)

    def create_supplier(self, ctx: UserContext, data: SupplierInput) -> Supplier:
        ctx.require(Permission.SUPPLIERS_EDIT)
        nom, telephone, adresse = _clean(data)
        with transaction(self._conn):
            if self._suppliers.get_by_name(nom) is not None:
                raise BusinessRuleError("Un fournisseur porte déjà ce nom.")
            supplier_id = self._suppliers.insert(nom, telephone, adresse, ctx.user_id)
            self._audit.add(
                user_id=ctx.user_id,
                action="SUPPLIER_CREATED",
                entity_type="supplier",
                entity_id=supplier_id,
                details={"nom": nom},
            )
            supplier = self._suppliers.get(supplier_id)
        assert supplier is not None
        return supplier

    def update_supplier(self, ctx: UserContext, supplier_id: int, data: SupplierInput) -> Supplier:
        ctx.require(Permission.SUPPLIERS_EDIT)
        nom, telephone, adresse = _clean(data)
        with transaction(self._conn):
            self._require(supplier_id)
            other = self._suppliers.get_by_name(nom)
            if other is not None and other.id != supplier_id:
                raise BusinessRuleError("Un fournisseur porte déjà ce nom.")
            self._suppliers.update(supplier_id, nom, telephone, adresse)
            self._audit.add(
                user_id=ctx.user_id,
                action="SUPPLIER_UPDATED",
                entity_type="supplier",
                entity_id=supplier_id,
                details={"nom": nom},
            )
            supplier = self._suppliers.get(supplier_id)
        assert supplier is not None
        return supplier

    def set_active(self, ctx: UserContext, supplier_id: int, active: bool) -> Supplier:
        ctx.require(Permission.SUPPLIERS_EDIT)
        with transaction(self._conn):
            self._require(supplier_id)
            self._suppliers.set_status(supplier_id, "ACTIF" if active else "INACTIF")
            self._audit.add(
                user_id=ctx.user_id,
                action="SUPPLIER_REACTIVATED" if active else "SUPPLIER_DEACTIVATED",
                entity_type="supplier",
                entity_id=supplier_id,
            )
            supplier = self._suppliers.get(supplier_id)
        assert supplier is not None
        return supplier

    def _require(self, supplier_id: int) -> Supplier:
        supplier = self._suppliers.get(supplier_id)
        if supplier is None:
            raise BusinessRuleError("Fournisseur introuvable.")
        return supplier