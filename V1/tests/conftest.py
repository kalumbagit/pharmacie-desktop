import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core import security as passwords
from app.core.database import connect, migrate
from app.core.security import UserContext
from app.services.auth import AuthService
from app.services.users import UserService


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coût bcrypt minimal pour accélérer les tests."""
    monkeypatch.setattr(passwords, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection]:
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Base avec toutes les migrations appliquées."""
    migrate(conn)
    return conn


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def auth(db: sqlite3.Connection, clock: FakeClock) -> AuthService:
    return AuthService(db, clock)


@pytest.fixture
def users(db: sqlite3.Connection) -> UserService:
    return UserService(db)


@pytest.fixture
def admin_ctx(auth: AuthService) -> UserContext:
    auth.create_first_admin("admin", "Dupont", "Marie", "Admin2026x")
    return auth.login("admin", "Admin2026x")


def make_active_user(
    auth: AuthService, users: UserService, admin: UserContext, identifiant: str, role: str
) -> UserContext:
    """Crée un utilisateur et le fait passer par sa première connexion."""
    created = users.create_user(
        admin, identifiant=identifiant, nom="Test", prenom="User", role_code=role
    )
    ctx = auth.login(identifiant, created.temporary_password)
    return auth.change_password(ctx, created.temporary_password, "NouveauPass1")


# --- Étape 4 : produits, fournisseurs, lots ---------------------------------------
from app.services.lots import LotService  # noqa: E402
from app.services.products import ProductInput, ProductService  # noqa: E402
from app.services.suppliers import SupplierInput, SupplierService  # noqa: E402


@pytest.fixture
def products(db: sqlite3.Connection) -> ProductService:
    return ProductService(db)


@pytest.fixture
def suppliers(db: sqlite3.Connection) -> SupplierService:
    return SupplierService(db)


@pytest.fixture
def lots(db: sqlite3.Connection, clock: FakeClock) -> LotService:
    return LotService(db, clock)


@pytest.fixture
def pharma_ctx(auth: AuthService, users: UserService, admin_ctx: UserContext) -> UserContext:
    return make_active_user(auth, users, admin_ctx, "pharma1", "PHARMACIEN")


@pytest.fixture
def caisse_ctx(auth: AuthService, users: UserService, admin_ctx: UserContext) -> UserContext:
    return make_active_user(auth, users, admin_ctx, "caisse1", "CAISSIER")


def product_input(code: str = "PARA500", **overrides: object) -> ProductInput:
    values: dict[str, object] = {
        "code": code,
        "nom_commercial": "Paracétamol 500 mg",
        "unite_vente": "Boîte",
        "prix_achat_indicatif": 600,
        "prix_vente": 1000,
    }
    values.update(overrides)
    return ProductInput(**values)  # type: ignore[arg-type]


@pytest.fixture
def product(products: ProductService, admin_ctx: UserContext):  # noqa: ANN201
    """Produit sans sous-unité."""
    return products.create_product(admin_ctx, product_input())


@pytest.fixture
def product_sub(products: ProductService, admin_ctx: UserContext):  # noqa: ANN201
    """Boîte de 10 plaquettes vendable à la plaquette."""
    return products.create_product(
        admin_ctx,
        product_input(
            "AMOX500",
            nom_commercial="Amoxicilline 500 mg",
            sous_unite="Plaquette",
            sous_unites_par_unite=10,
            prix_vente=5000,
            prix_vente_sous_unite=600,
        ),
    )


@pytest.fixture
def supplier(suppliers: SupplierService, admin_ctx: UserContext):  # noqa: ANN201
    return suppliers.create_supplier(admin_ctx, SupplierInput(nom="Laborex Cameroun"))


def stock_is_consistent(conn: sqlite3.Connection) -> bool:
    """Réconciliation : quantité du lot == somme de ses mouvements, pour tous les lots."""
    rows = conn.execute(
        "SELECT l.id FROM lots l WHERE l.quantite_disponible != "
        "COALESCE((SELECT SUM(quantite_signee) FROM stock_movements m WHERE m.lot_id = l.id), 0)"
    ).fetchall()
    return not rows