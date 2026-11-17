import sqlite3

import pytest

from app.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from app.core.security import UserContext
from app.services.suppliers import SupplierInput, SupplierService


def test_create_supplier(suppliers: SupplierService, admin_ctx: UserContext) -> None:
    created = suppliers.create_supplier(
        admin_ctx, SupplierInput(nom="  UBIPHARM   Cameroun ", telephone="+237 6 99 00 11 22")
    )
    assert created.nom == "UBIPHARM Cameroun"
    assert created.is_active


def test_name_is_unique_case_insensitive(
    suppliers: SupplierService, admin_ctx: UserContext, supplier
) -> None:
    with pytest.raises(BusinessRuleError):
        suppliers.create_supplier(admin_ctx, SupplierInput(nom="LABOREX CAMEROUN"))


def test_update_cannot_take_another_name(
    suppliers: SupplierService, admin_ctx: UserContext, supplier
) -> None:
    other = suppliers.create_supplier(admin_ctx, SupplierInput(nom="Autre"))
    with pytest.raises(BusinessRuleError):
        suppliers.update_supplier(admin_ctx, other.id, SupplierInput(nom="laborex cameroun"))
    # garder son propre nom est permis
    suppliers.update_supplier(admin_ctx, other.id, SupplierInput(nom="Autre", adresse="Douala"))


@pytest.mark.parametrize(
    "data",
    [
        SupplierInput(nom=""),
        SupplierInput(nom="x" * 121),
        SupplierInput(nom="A", telephone="abc"),
        SupplierInput(nom="A", adresse="x" * 201),
    ],
)
def test_invalid_input(suppliers: SupplierService, admin_ctx: UserContext, data) -> None:
    with pytest.raises(ValidationError):
        suppliers.create_supplier(admin_ctx, data)


def test_edit_requires_permission(
    suppliers: SupplierService, pharma_ctx: UserContext, caisse_ctx: UserContext, supplier
) -> None:
    assert suppliers.list_suppliers(pharma_ctx)  # le pharmacien consulte
    for ctx in (pharma_ctx, caisse_ctx):
        with pytest.raises(PermissionDeniedError):
            suppliers.create_supplier(ctx, SupplierInput(nom="Nouveau"))
        with pytest.raises(PermissionDeniedError):
            suppliers.set_active(ctx, supplier.id, False)
    with pytest.raises(PermissionDeniedError):
        suppliers.list_suppliers(caisse_ctx)


def test_deactivate_filter_and_no_delete(
    db: sqlite3.Connection, suppliers: SupplierService, admin_ctx: UserContext, supplier
) -> None:
    assert not suppliers.set_active(admin_ctx, supplier.id, False).is_active
    assert suppliers.list_suppliers(admin_ctx, statut="ACTIF") == []
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM suppliers WHERE id = ?", (supplier.id,))