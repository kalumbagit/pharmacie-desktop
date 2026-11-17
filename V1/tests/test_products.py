import sqlite3

import pytest

from app.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from app.core.security import UserContext
from app.services.lots import LotService
from app.services.products import ProductService
from tests.conftest import make_active_user, product_input


def test_create_product_normalizes_code(products: ProductService, admin_ctx: UserContext) -> None:
    created = products.create_product(admin_ctx, product_input("para.500"))
    assert created.code == "PARA.500"
    assert created.sous_unites_par_unite == 1
    assert created.prix_vente_sous_unite is None


def test_code_is_unique_case_insensitive(
    products: ProductService, admin_ctx: UserContext, product
) -> None:
    with pytest.raises(BusinessRuleError):
        products.create_product(admin_ctx, product_input("para500"))


def test_barcode_is_unique(products: ProductService, admin_ctx: UserContext) -> None:
    products.create_product(admin_ctx, product_input("A1", code_barres="6001234567"))
    with pytest.raises(BusinessRuleError):
        products.create_product(admin_ctx, product_input("A2", code_barres="6001234567"))


def test_find_by_barcode(products: ProductService, admin_ctx: UserContext) -> None:
    created = products.create_product(admin_ctx, product_input("A1", code_barres="6001234567"))
    found = products.find_by_barcode(admin_ctx, " 6001234567 ")
    assert found is not None and found.id == created.id
    assert products.find_by_barcode(admin_ctx, "0000000000") is None


@pytest.mark.parametrize("code", ["", "a b", "x" * 31, "é1"])
def test_invalid_code_rejected(products: ProductService, admin_ctx: UserContext, code: str) -> None:
    with pytest.raises(ValidationError):
        products.create_product(admin_ctx, product_input(code))


@pytest.mark.parametrize("price", [-1, 100_000_001])
def test_invalid_price_rejected(
    products: ProductService, admin_ctx: UserContext, price: int
) -> None:
    with pytest.raises(ValidationError):
        products.create_product(admin_ctx, product_input("A1", prix_vente=price))


def test_sub_unit_requires_at_least_two_per_unit(
    products: ProductService, admin_ctx: UserContext
) -> None:
    with pytest.raises(ValidationError):
        products.create_product(
            admin_ctx, product_input("A1", sous_unite="Plaquette", sous_unites_par_unite=1)
        )


def test_sub_unit_product_fields(products: ProductService, product_sub) -> None:
    assert product_sub.has_sous_unite
    assert product_sub.sous_unites_par_unite == 10
    assert product_sub.prix_vente_sous_unite == 600
    assert product_sub.to_base(3, "UNITE") == 30
    assert product_sub.to_base(3, "SOUS_UNITE") == 3


def test_to_base_rejects_sub_unit_when_none(product) -> None:
    with pytest.raises(ValueError):
        product.to_base(1, "SOUS_UNITE")


def test_pharmacien_and_caissier_cannot_edit_products(
    products: ProductService, pharma_ctx: UserContext, caisse_ctx: UserContext, product
) -> None:
    for ctx in (pharma_ctx, caisse_ctx):
        with pytest.raises(PermissionDeniedError):
            products.create_product(ctx, product_input("B1"))
        with pytest.raises(PermissionDeniedError):
            products.update_product(ctx, product.id, product_input())
        with pytest.raises(PermissionDeniedError):
            products.set_active(ctx, product.id, False)


def test_view_permissions(
    products: ProductService, pharma_ctx: UserContext, caisse_ctx: UserContext, product
) -> None:
    assert products.list_products(pharma_ctx)
    assert products.list_products(caisse_ctx)


def test_price_change_requires_price_permission(
    db: sqlite3.Connection,
    auth,
    users,
    admin_ctx: UserContext,
    products: ProductService,
    product,
) -> None:
    """Un rôle qui peut éditer les produits mais pas les prix ne peut pas changer un prix."""
    db.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = 'products.edit' "
        "WHERE r.code = 'PHARMACIEN'"
    )
    editor = make_active_user(auth, users, admin_ctx, "pharma2", "PHARMACIEN")
    with pytest.raises(PermissionDeniedError):
        products.update_product(editor, product.id, product_input(prix_vente=2000))
    # même prix : la modification d'un autre champ reste permise
    updated = products.update_product(editor, product.id, product_input(dosage="500 mg"))
    assert updated.dosage == "500 mg"
    assert updated.prix_vente == 1000


def test_update_unknown_product(products: ProductService, admin_ctx: UserContext) -> None:
    with pytest.raises(BusinessRuleError):
        products.update_product(admin_ctx, 9999, product_input())


def test_deactivate_and_reactivate(
    products: ProductService, admin_ctx: UserContext, product
) -> None:
    assert not products.set_active(admin_ctx, product.id, False).is_active
    assert [p.id for p in products.list_products(admin_ctx, statut="INACTIF")] == [product.id]
    assert products.set_active(admin_ctx, product.id, True).is_active


def test_packaging_locked_once_lots_exist(
    products: ProductService,
    lots: LotService,
    admin_ctx: UserContext,
    product_sub,
    supplier,
) -> None:
    changed = product_input(
        "AMOX500",
        nom_commercial="Amoxicilline 500 mg",
        sous_unite="Plaquette",
        sous_unites_par_unite=12,
        prix_vente=5000,
        prix_vente_sous_unite=600,
    )
    products.update_product(admin_ctx, product_sub.id, changed)  # pas encore de lot : OK
    lots.receive_stock(
        admin_ctx,
        product_id=product_sub.id,
        supplier_id=supplier.id,
        numero_lot="L1",
        date_peremption="2028-01-31",
        quantite=1,
    )
    with pytest.raises(BusinessRuleError):
        products.update_product(
            admin_ctx,
            product_sub.id,
            product_input(
                "AMOX500",
                nom_commercial="Amoxicilline 500 mg",
                sous_unite="Plaquette",
                sous_unites_par_unite=10,
                prix_vente=5000,
                prix_vente_sous_unite=600,
            ),
        )
    assert products.has_lots(admin_ctx, product_sub.id)


def test_packaging_locked_at_sql_level(
    db: sqlite3.Connection, product_sub, lots, admin_ctx, supplier
) -> None:
    lots.receive_stock(
        admin_ctx,
        product_id=product_sub.id,
        supplier_id=supplier.id,
        numero_lot="L1",
        date_peremption="2028-01-31",
        quantite=1,
    )
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE products SET sous_unites_par_unite = 20 WHERE id = ?", (product_sub.id,))


def test_product_cannot_be_deleted(db: sqlite3.Connection, product) -> None:
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM products WHERE id = ?", (product.id,))


def test_audit_trail_on_product_creation(db: sqlite3.Connection, product) -> None:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM audit_log WHERE action = 'PRODUCT_CREATED' AND entity_id = ?",
        (product.id,),
    ).fetchone()
    assert row["n"] == 1


@pytest.mark.xfail(
    strict=True,
    reason="Constat étape 4b : le caissier reçoit le prix d'achat indicatif (donnée de marge).",
)
def test_cashier_does_not_get_purchase_price(
    products: ProductService, caisse_ctx: UserContext, product
) -> None:
    seen = products.list_products(caisse_ctx)[0]
    assert seen.prix_achat_indicatif in (0, None)