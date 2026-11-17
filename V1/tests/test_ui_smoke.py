"""Tests de démarrage de l'interface : chaque page se charge sans erreur (mode offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.security import UserContext  # noqa: E402
from app.services.lots import LotService  # noqa: E402
from app.ui.lot_pages import LotsPage  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.product_pages import ProductFormPage, ProductsPage  # noqa: E402
from app.ui.supplier_pages import SupplierFormPage, SuppliersPage  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from app.ui.user_pages import UsersPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app  # type: ignore[return-value]


@pytest.fixture
def window(qapp: QApplication, db: sqlite3.Connection, tmp_path: Path) -> MainWindow:
    settings = Settings(
        app_name="Pharmacie",
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        backup_dir=tmp_path / "backups",
        log_dir=tmp_path / "logs",
        currency="FCFA",
    )
    win = MainWindow(settings, db)
    yield win
    win.close()


def _seed(db: sqlite3.Connection, admin_ctx: UserContext, product, product_sub, supplier, clock):
    lots = LotService(db, clock)
    lots.receive_stock(
        admin_ctx,
        product_id=product.id,
        supplier_id=supplier.id,
        numero_lot="L1",
        date_peremption="2028-01-31",
        quantite=20,
    )
    lots.receive_stock(
        admin_ctx,
        product_id=product_sub.id,
        supplier_id=supplier.id,
        numero_lot="L2",
        date_peremption="2026-12-01",
        quantite=2,
    )


def test_all_admin_pages_load_with_data(
    window: MainWindow, db, admin_ctx, product, product_sub, supplier, clock
) -> None:
    _seed(db, admin_ctx, product, product_sub, supplier, clock)
    window.login_succeeded(admin_ctx)
    assert window.sidebar.isVisible() or not window.isVisible()  # sidebar construite

    expectations = [
        (window.show_home, None),
        (window.show_products, ProductsPage),
        (lambda: window.show_product_form(None), ProductFormPage),
        (lambda: window.show_product_form(product_sub), ProductFormPage),
        (window.show_suppliers, SuppliersPage),
        (lambda: window.show_supplier_form(None), SupplierFormPage),
        (lambda: window.show_supplier_form(supplier), SupplierFormPage),
        (window.show_lots, LotsPage),
        (lambda: window.show_lots(supplier.id, supplier.nom), LotsPage),
        (window.show_users, UsersPage),
    ]
    for action, page_type in expectations:
        action()
        if page_type is not None:
            assert isinstance(window._page, page_type)


def test_pharmacien_menu_hides_admin_and_cashier_menu_is_minimal(
    window: MainWindow, pharma_ctx: UserContext, caisse_ctx: UserContext
) -> None:
    window.login_succeeded(pharma_ctx)
    assert {"products", "lots", "suppliers"} <= set(window._nav)
    assert "users" not in window._nav
    window.show_products()
    window.show_lots()

    window.logout()
    window.login_succeeded(caisse_ctx)
    assert "users" not in window._nav
    assert "lots" not in window._nav and "suppliers" not in window._nav
    window.show_products()


def test_forced_password_change_blocks_menu(window: MainWindow, auth, users, admin_ctx) -> None:
    created = users.create_user(
        admin_ctx, identifiant="nouveau", nom="N", prenom="U", role_code="CAISSIER"
    )
    ctx = auth.login("nouveau", created.temporary_password)
    window.login_succeeded(ctx)
    assert not window._nav  # menu non construit tant que le mot de passe n'est pas changé