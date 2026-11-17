import sqlite3
from datetime import date

import pytest

from app.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from app.core.security import UserContext
from app.models import Lot
from app.services.lots import LotService, lot_etat
from app.services.suppliers import SupplierInput, SupplierService
from tests.conftest import stock_is_consistent

TODAY = date(2026, 11, 12)


def receive(lots: LotService, ctx: UserContext, product, supplier, **overrides):  # noqa: ANN001, ANN201
    values = {
        "product_id": product.id,
        "supplier_id": supplier.id,
        "numero_lot": "L001",
        "date_peremption": "2028-06-30",
        "quantite": 10,
    }
    values.update(overrides)
    return lots.receive_stock(ctx, **values)


def _lot(**overrides: object) -> Lot:
    base = dict(
        id=1,
        product_id=1,
        product_code="P",
        product_nom="P",
        product_unite_vente="Boîte",
        product_sous_unite=None,
        product_par_unite=1,
        supplier_id=1,
        supplier_nom="F",
        numero_lot="L",
        date_fabrication=None,
        date_peremption="2028-01-01",
        date_reception="2026-01-01",
        quantite_recue=10,
        quantite_disponible=10,
        prix_achat_unitaire=0,
        statut="ACTIF",
    )
    base.update(overrides)
    return Lot(**base)  # type: ignore[arg-type]


# --- état d'un lot --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "OK"),
        ({"date_peremption": "2026-12-31"}, "PROCHE"),  # dans 49 jours
        ({"date_peremption": "2027-02-10"}, "PROCHE"),  # exactement 90 jours
        ({"date_peremption": "2027-02-11"}, "OK"),  # 91 jours
        ({"date_peremption": "2026-11-12"}, "PROCHE"),  # périme aujourd'hui : encore vendable
        ({"date_peremption": "2026-11-11"}, "EXPIRE"),
        ({"quantite_disponible": 0}, "EPUISE"),
        ({"statut": "BLOQUE"}, "BLOQUE"),
        ({"statut": "BLOQUE", "date_peremption": "2026-01-01"}, "EXPIRE"),
    ],
)
def test_lot_etat(overrides: dict, expected: str) -> None:
    assert lot_etat(_lot(**overrides), TODAY, 90) == expected


# --- réception ------------------------------------------------------------------------
def test_receive_creates_lot_and_movement(
    db: sqlite3.Connection, lots: LotService, admin_ctx: UserContext, product, supplier
) -> None:
    lot = receive(lots, admin_ctx, product, supplier, quantite=25, prix_achat_unitaire=600)
    assert lot.quantite_recue == lot.quantite_disponible == 25
    assert lot.etat == "OK"
    assert lot.prix_achat_unitaire == 600
    movements = lots.movements(admin_ctx, lot.id)
    assert [(m.type, m.quantite_signee, m.user_id) for m in movements] == [
        ("STOCK_INITIAL", 25, admin_ctx.user_id)
    ]
    assert stock_is_consistent(db)


def test_receive_in_sub_units_and_units(
    db: sqlite3.Connection, lots: LotService, admin_ctx: UserContext, product_sub, supplier
) -> None:
    boxes = receive(lots, admin_ctx, product_sub, supplier, numero_lot="B1", quantite=3)
    assert boxes.quantite_disponible == 30  # 3 boîtes x 10 plaquettes
    plaquettes = receive(
        lots,
        admin_ctx,
        product_sub,
        supplier,
        numero_lot="B2",
        quantite=7,
        conditionnement="SOUS_UNITE",
    )
    assert plaquettes.quantite_disponible == 7
    assert stock_is_consistent(db)


def test_sub_unit_reception_refused_without_sub_unit(
    lots: LotService, admin_ctx: UserContext, product, supplier
) -> None:
    with pytest.raises(ValidationError):
        receive(lots, admin_ctx, product, supplier, conditionnement="SOUS_UNITE")


def test_second_reception_feeds_same_lot(
    db: sqlite3.Connection, lots: LotService, admin_ctx: UserContext, product, supplier
) -> None:
    receive(lots, admin_ctx, product, supplier, quantite=10)
    lot = receive(lots, admin_ctx, product, supplier, quantite=5)
    assert (lot.quantite_recue, lot.quantite_disponible) == (15, 15)
    assert db.execute("SELECT COUNT(*) FROM lots").fetchone()[0] == 1
    assert len(lots.movements(admin_ctx, lot.id)) == 2
    assert stock_is_consistent(db)


def test_same_number_other_supplier_or_expiry_refused(
    lots: LotService, suppliers: SupplierService, admin_ctx: UserContext, product, supplier
) -> None:
    receive(lots, admin_ctx, product, supplier)
    other = suppliers.create_supplier(admin_ctx, SupplierInput(nom="Autre fournisseur"))
    with pytest.raises(BusinessRuleError):
        receive(lots, admin_ctx, product, other)
    with pytest.raises(BusinessRuleError):
        receive(lots, admin_ctx, product, supplier, date_peremption="2029-01-01")


def test_same_lot_number_allowed_for_different_products(
    lots: LotService, admin_ctx: UserContext, product, product_sub, supplier
) -> None:
    receive(lots, admin_ctx, product, supplier)
    receive(lots, admin_ctx, product_sub, supplier)  # même numéro « L001 »


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"quantite": 0}, ValidationError),
        ({"quantite": -5}, ValidationError),
        ({"quantite": 1.5}, ValidationError),
        ({"numero_lot": "   "}, ValidationError),
        ({"numero_lot": "x" * 51}, ValidationError),
        ({"prix_achat_unitaire": -1}, ValidationError),
        ({"date_peremption": "31/12/2028"}, ValidationError),
        ({"date_peremption": "2026-11-12"}, BusinessRuleError),  # périme aujourd'hui
        ({"date_peremption": "2025-01-01"}, BusinessRuleError),  # déjà périmé
        ({"date_reception": "2026-11-20"}, ValidationError),  # futur
        ({"date_fabrication": "2028-07-01"}, ValidationError),  # après la péremption
        ({"date_fabrication": "2026-11-13", "date_reception": "2026-11-12"}, ValidationError),
        ({"conditionnement": "CARTON"}, ValidationError),
    ],
)
def test_invalid_receptions_leave_no_trace(
    db: sqlite3.Connection,
    lots: LotService,
    admin_ctx: UserContext,
    product,
    supplier,
    overrides: dict,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        receive(lots, admin_ctx, product, supplier, **overrides)
    assert db.execute("SELECT COUNT(*) FROM lots").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0] == 0


def test_inactive_product_or_supplier_refused_with_full_rollback(
    db: sqlite3.Connection, lots: LotService, suppliers, products, admin_ctx, product, supplier
) -> None:
    suppliers.set_active(admin_ctx, supplier.id, False)
    with pytest.raises(BusinessRuleError):
        receive(lots, admin_ctx, product, supplier)
    suppliers.set_active(admin_ctx, supplier.id, True)
    products.set_active(admin_ctx, product.id, False)
    with pytest.raises(BusinessRuleError):
        receive(lots, admin_ctx, product, supplier)
    assert db.execute("SELECT COUNT(*) FROM lots").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0] == 0


def test_failure_after_lot_insert_rolls_back_everything(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, supplier, monkeypatch
) -> None:
    """Si le mouvement échoue après la création du lot, le lot disparaît aussi."""

    def boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(lots._movements, "insert", boom)
    with pytest.raises(RuntimeError):
        receive(lots, admin_ctx, product, supplier)
    assert db.execute("SELECT COUNT(*) FROM lots").fetchone()[0] == 0
    assert not db.in_transaction


def test_receive_internal_rejects_non_entry_types(
    lots: LotService, admin_ctx: UserContext, product, supplier
) -> None:
    with pytest.raises(ValidationError):
        lots.receive_internal(
            admin_ctx.user_id,
            product_id=product.id,
            supplier_id=supplier.id,
            numero_lot="L1",
            date_peremption="2028-01-01",
            quantite=1,
            movement_type="VENTE",
        )


# --- permissions ----------------------------------------------------------------------
def test_manual_reception_permissions(
    lots: LotService, pharma_ctx: UserContext, caisse_ctx: UserContext, product, supplier
) -> None:
    receive(lots, pharma_ctx, product, supplier)  # le pharmacien a stock.adjust
    with pytest.raises(PermissionDeniedError):
        receive(lots, caisse_ctx, product, supplier, numero_lot="L2")


def test_cashier_cannot_view_lots(lots: LotService, caisse_ctx: UserContext) -> None:
    with pytest.raises(PermissionDeniedError):
        lots.list_lots(caisse_ctx)
    with pytest.raises(PermissionDeniedError):
        lots.get_lot(caisse_ctx, 1)
    with pytest.raises(PermissionDeniedError):
        lots.movements(caisse_ctx, 1)


# --- consultation ---------------------------------------------------------------------
def test_list_filters_and_order(
    lots: LotService, admin_ctx, product, product_sub, supplier, suppliers
) -> None:
    receive(lots, admin_ctx, product, supplier, numero_lot="TARD", date_peremption="2029-01-01")
    receive(lots, admin_ctx, product, supplier, numero_lot="TOT", date_peremption="2026-12-15")
    receive(lots, admin_ctx, product_sub, supplier, numero_lot="X", date_peremption="2028-01-01")

    listed = lots.list_lots(admin_ctx)
    assert [lot.numero_lot for lot in listed] == ["TOT", "X", "TARD"]  # ordre de péremption
    assert [lot.numero_lot for lot in lots.list_lots(admin_ctx, etat="PROCHE")] == ["TOT"]
    assert len(lots.list_lots(admin_ctx, etat="VENDABLE")) == 3
    assert len(lots.list_lots(admin_ctx, product_id=product.id)) == 2
    assert len(lots.list_lots(admin_ctx, supplier_id=supplier.id)) == 3
    assert [lot.numero_lot for lot in lots.list_lots(admin_ctx, search="tard")] == ["TARD"]


def test_search_treats_wildcards_literally(lots: LotService, admin_ctx, product, supplier) -> None:
    receive(lots, admin_ctx, product, supplier, numero_lot="AB-1")
    assert lots.list_lots(admin_ctx, search="%") == []
    assert lots.list_lots(admin_ctx, search="_") == []


def test_alert_threshold_is_configurable(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, supplier
) -> None:
    receive(lots, admin_ctx, product, supplier, date_peremption="2027-03-01")  # dans ~109 j
    assert lots.list_lots(admin_ctx)[0].etat == "OK"
    db.execute("UPDATE app_settings SET valeur = '120' WHERE cle = 'peremption_alerte_jours'")
    assert lots.list_lots(admin_ctx)[0].etat == "PROCHE"


def test_unknown_lot(lots: LotService, admin_ctx: UserContext) -> None:
    with pytest.raises(BusinessRuleError):
        lots.get_lot(admin_ctx, 999)


# --- blocage --------------------------------------------------------------------------
def test_block_and_unblock(
    lots: LotService, admin_ctx, pharma_ctx, caisse_ctx, product, supplier
) -> None:
    lot = receive(lots, admin_ctx, product, supplier)
    with pytest.raises(ValidationError):
        lots.set_blocked(admin_ctx, lot.id, True, "  ")  # motif obligatoire
    with pytest.raises(PermissionDeniedError):
        lots.set_blocked(caisse_ctx, lot.id, True, "rappel")
    assert lots.set_blocked(pharma_ctx, lot.id, True, "Rappel fabricant").etat == "BLOQUE"
    assert lots.list_lots(admin_ctx, etat="VENDABLE") == []
    with pytest.raises(BusinessRuleError):  # pas de réception dans un lot bloqué
        receive(lots, admin_ctx, product, supplier, quantite=1)
    assert lots.set_blocked(pharma_ctx, lot.id, False).etat == "OK"
    receive(lots, admin_ctx, product, supplier, quantite=1)


# --- garanties au niveau SQL (même un bug de service ne peut pas les contourner) ------
def test_quantity_cannot_be_edited_directly(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, supplier
) -> None:
    lot = receive(lots, admin_ctx, product, supplier, quantite=10)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE lots SET quantite_disponible = 999 WHERE id = ?", (lot.id,))
    assert lots.get_lot(admin_ctx, lot.id).quantite_disponible == 10


def test_movements_are_immutable(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, supplier
) -> None:
    receive(lots, admin_ctx, product, supplier)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE stock_movements SET quantite_signee = 1")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM stock_movements")


def _insert_movement(db: sqlite3.Connection, lot: Lot, qty: int, user_id: int, mtype: str) -> None:
    db.execute(
        "INSERT INTO stock_movements (type, product_id, lot_id, quantite_signee, user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (mtype, lot.product_id, lot.id, qty, user_id),
    )


def test_stock_can_never_go_negative(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, supplier
) -> None:
    lot = receive(lots, admin_ctx, product, supplier, quantite=10)
    with pytest.raises(sqlite3.DatabaseError):
        _insert_movement(db, lot, -11, admin_ctx.user_id, "VENTE")
    assert lots.get_lot(admin_ctx, lot.id).quantite_disponible == 10
    _insert_movement(db, lot, -10, admin_ctx.user_id, "VENTE")  # sortie exacte : permise
    assert lots.get_lot(admin_ctx, lot.id).etat == "EPUISE"
    assert stock_is_consistent(db)


def test_movement_must_match_lot_product(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, product_sub, supplier
) -> None:
    lot = receive(lots, admin_ctx, product, supplier)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute(
            "INSERT INTO stock_movements (type, product_id, lot_id, quantite_signee, user_id) "
            "VALUES ('AJUSTEMENT_POSITIF', ?, ?, 1, ?)",
            (product_sub.id, lot.id, admin_ctx.user_id),
        )


def test_lot_cannot_be_deleted_or_change_product(
    db: sqlite3.Connection, lots: LotService, admin_ctx, product, product_sub, supplier
) -> None:
    lot = receive(lots, admin_ctx, product, supplier)
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM lots WHERE id = ?", (lot.id,))
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE lots SET product_id = ? WHERE id = ?", (product_sub.id, lot.id))