"""Fenêtre unique de l'application.

Un seul écran principal : menu latéral à gauche (visible une fois connecté) et zone de
contenu à droite. Chaque action vide la zone de contenu et y charge la page voulue
(`navigate`). Aucune autre fenêtre : connexion, formulaires et listes sont des pages.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import Permission, UserContext
from app.models import Lot, Product, Supplier, User
from app.services.app_settings import AppSettingsService
from app.services.auth import AuthService
from app.services.cash import CashService
from app.services.dashboard import DashboardService
from app.services.inventory import InventoryService
from app.services.invoices import InvoiceService
from app.services.lots import LotService
from app.services.products import ProductService
from app.services.sales import SaleResult, SaleService
from app.services.suppliers import SupplierService
from app.services.users import UserService
from app.ui.auth_pages import ChangePasswordPage, LoginPage, SetupPage
from app.ui.cash_pages import CashClosePage, CashOpenPage, CashPage, SaleDonePage
from app.ui.home_page import HomePage
from app.ui.inventory_pages import InventoryPage
from app.ui.lot_pages import (
    LotAddPage,
    LotEditPage,
    LotReceivePage,
    LotsPage,
    SupplierHistoryPage,
)
from app.ui.product_pages import ProductFormPage, ProductsPage
from app.ui.sales_pages import SaleDetailPage, SalesPage
from app.ui.settings_page import SettingsPage
from app.ui.supplier_pages import SupplierFormPage, SuppliersPage
from app.ui.theme import make_label
from app.ui.user_pages import TempPasswordPage, UserFormPage, UsersPage


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.settings = settings
        self.conn = conn
        self.auth = AuthService(conn)
        self.users = UserService(conn)
        self.products = ProductService(conn)
        self.suppliers = SupplierService(conn)
        self.lots = LotService(conn)
        self.inventory = InventoryService(conn)
        self.cash = CashService(conn)
        self.sales = SaleService(conn)
        self.invoices = InvoiceService(
            conn,
            settings.documents_dir,
        )
        self.dashboard = DashboardService(conn)
        self.app_settings = AppSettingsService(conn)

        self._ctx: UserContext | None = None
        self._page: QWidget | None = None
        self._nav: dict[str, QPushButton] = {}

        self.setWindowTitle(settings.app_name)
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(230)
        self._sidebar_layout = QVBoxLayout(self.sidebar)
        self._sidebar_layout.setContentsMargins(14, 18, 14, 14)
        self._sidebar_layout.setSpacing(6)

        self.content = QWidget()
        self.content.setObjectName("content")
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(28, 24, 28, 24)

        root.addWidget(self.sidebar)
        root.addWidget(self.content, 1)
        self.setCentralWidget(central)
        self.sidebar.hide()

        self.start()

    # --- état de session -----------------------------------------------------------

    @property
    def ctx(self) -> UserContext:
        if self._ctx is None:
            raise RuntimeError("Aucun utilisateur connecté.")
        return self._ctx

    # --- zone de contenu -----------------------------------------------------------

    def navigate(self, page: QWidget) -> None:
        """Vide la zone de contenu et y charge `page`."""
        if self._page is not None:
            self._content_layout.removeWidget(self._page)
            self._page.hide()
            self._page.deleteLater()

        self._page = page
        self._content_layout.addWidget(page)

    # --- parcours d'accès ----------------------------------------------------------

    def start(self) -> None:
        if self.auth.needs_setup():
            self.show_setup()
        else:
            self.show_login()

    def show_setup(self) -> None:
        self.navigate(SetupPage(self))

    def show_login(self) -> None:
        self.navigate(LoginPage(self))

    def login_succeeded(self, ctx: UserContext) -> None:
        self._ctx = ctx
        if ctx.must_change_password:
            self.show_change_password(forced=True)
        else:
            self._enter_app()

    def password_changed(self, ctx: UserContext) -> None:
        self._ctx = ctx
        self._enter_app()

    def logout(self) -> None:
        self._ctx = None
        self.sidebar.hide()
        self.show_login()

    def _enter_app(self) -> None:
        self._build_sidebar()
        self.sidebar.show()
        self.show_home()

    # --- pages de l'application ----------------------------------------------------

    def show_home(self) -> None:
        self._set_active("home")
        self.navigate(HomePage(self))

    # Caisse et ventes

    def show_cash(self) -> None:
        """Point de vente si une caisse est ouverte, sinon écran d'ouverture."""
        self._set_active("cash")
        try:
            session = self.cash.get_open_session(self.ctx)
        except AppError:
            session = None

        self.navigate(
            CashPage(self, session) if session else CashOpenPage(self)
        )

    def show_cash_close(self) -> None:
        self._set_active("cash")
        try:
            session = self.cash.get_open_session(self.ctx)
            if session is None:
                self.show_cash()
                return

            summary = self.cash.summary(self.ctx, session.id)
        except AppError:
            self.show_cash()
            return

        self.navigate(CashClosePage(self, summary))

    def show_sale_done(self, result: SaleResult) -> None:
        self._set_active("cash")
        self.navigate(SaleDonePage(self, result))

    def show_sales(self) -> None:
        self._set_active("sales")
        self.navigate(SalesPage(self))

    def show_sale_detail(self, sale_id: int) -> None:
        self._set_active("sales")
        self.navigate(SaleDetailPage(self, sale_id))

    # Catalogue et stock

    def show_products(self) -> None:
        self._set_active("products")
        self.navigate(ProductsPage(self))

    def show_product_form(self, product: Product | None = None) -> None:
        self._set_active("products")
        self.navigate(ProductFormPage(self, product))

    def show_suppliers(self) -> None:
        self._set_active("suppliers")
        self.navigate(SuppliersPage(self))

    def show_supplier_form(
        self,
        supplier: Supplier | None = None,
    ) -> None:
        self._set_active("suppliers")
        self.navigate(SupplierFormPage(self, supplier))

    def show_supplier_history(
        self,
        supplier_id: int,
        supplier_nom: str,
    ) -> None:
        """Ouvre l'historique des transactions d'un fournisseur."""
        self._set_active("suppliers")
        self.navigate(
            SupplierHistoryPage(self, supplier_id, supplier_nom)
        )

    def show_lots(
        self,
        supplier_id: int | None = None,
        supplier_nom: str | None = None,
    ) -> None:
        # Vue filtrée sur un fournisseur : entrée « Fournisseurs » du menu.
        self._set_active(
            "lots" if supplier_id is None else "suppliers"
        )
        self.navigate(
            LotsPage(
                self,
                supplier_id=supplier_id,
                supplier_nom=supplier_nom,
            )
        )

    def show_lot_receive(self) -> None:
        self._set_active("lots")
        self.navigate(LotReceivePage(self))

    def show_lot_add(self, lot: Lot) -> None:
        self._set_active("lots")
        self.navigate(LotAddPage(self, lot))

    def show_lot_edit(self, lot: Lot) -> None:
        self._set_active("lots")
        self.navigate(LotEditPage(self, lot))

    def show_inventory(self) -> None:
        self._set_active("inventory")
        self.navigate(InventoryPage(self))

    # Administration

    def show_users(self) -> None:
        self._set_active("users")
        self.navigate(UsersPage(self))

    def show_user_form(self, user: User | None = None) -> None:
        self._set_active("users")
        self.navigate(UserFormPage(self, user))

    def show_temp_password(
        self,
        identifiant: str,
        password: str,
    ) -> None:
        self._set_active("users")
        self.navigate(
            TempPasswordPage(self, identifiant, password)
        )

    def show_settings(self) -> None:
        self._set_active("settings")
        self.navigate(SettingsPage(self))

    def show_change_password(self, forced: bool = False) -> None:
        self._set_active("")
        self.navigate(ChangePasswordPage(self, forced))

    # --- menu latéral --------------------------------------------------------------

    def _build_sidebar(self) -> None:
        while self._sidebar_layout.count():
            item = self._sidebar_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._nav.clear()

        ctx = self.ctx
        self._sidebar_layout.addWidget(
            make_label(self.settings.app_name, "appname")
        )
        self._sidebar_layout.addWidget(
            make_label(
                f"{ctx.nom_complet}\n{ctx.role_label}",
                "muted",
            )
        )
        self._sidebar_layout.addSpacing(14)

        self._add_nav("home", "Accueil", self.show_home)

        # Masquage ergonomique : les services contrôlent toujours les permissions.
        if ctx.has(Permission.SALES_CREATE):
            self._add_nav("cash", "Caisse", self.show_cash)

        if ctx.has(Permission.SALES_VIEW_OWN):
            self._add_nav("sales", "Ventes", self.show_sales)

        if ctx.has(Permission.PRODUCTS_VIEW):
            self._add_nav("products", "Produits", self.show_products)

        if ctx.has(Permission.LOTS_VIEW):
            self._add_nav("lots", "Lots", self.show_lots)

        if ctx.has(Permission.SUPPLIERS_VIEW):
            self._add_nav("suppliers", "Fournisseurs", self.show_suppliers)

        if ctx.has(Permission.REPORTS_STOCK):
            self._add_nav("inventory", "Inventaire", self.show_inventory)

        if ctx.has(Permission.USERS_MANAGE):
            self._add_nav("users", "Utilisateurs", self.show_users)

        if ctx.has(Permission.SETTINGS_EDIT):
            self._add_nav("settings", "Paramètres", self.show_settings)

        # Les prochains modules (approvisionnements, comptabilité...) s'ajoutent ici.

        self._sidebar_layout.addStretch(1)

        password = QPushButton("Mon mot de passe")
        password.setProperty("nav", "item")
        password.setCursor(Qt.CursorShape.PointingHandCursor)
        password.clicked.connect(
            lambda _checked=False: self.show_change_password(False)
        )
        self._sidebar_layout.addWidget(password)

        logout = QPushButton("Déconnexion")
        logout.setProperty("nav", "logout")
        logout.setCursor(Qt.CursorShape.PointingHandCursor)
        logout.clicked.connect(
            lambda _checked=False: self.logout()
        )
        self._sidebar_layout.addWidget(logout)

    def _add_nav(
        self,
        key: str,
        label: str,
        handler: Callable[[], None],
    ) -> None:
        button = QPushButton(label)
        button.setProperty("nav", "item")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(
            lambda _checked=False: handler()
        )
        self._sidebar_layout.addWidget(button)
        self._nav[key] = button

    def _set_active(self, key: str) -> None:
        for name, button in self._nav.items():
            button.setChecked(name == key)