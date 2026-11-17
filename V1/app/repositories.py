"""Accès aux données (tout le SQL). Un dépôt par agrégat ; à scinder par module
(produits, lots, ventes...) quand ce fichier deviendra trop long."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.models import (CashSession, Invoice, Lot, Payment, PaymentMethod, Product, Role, Sale,
    SaleLine, StockMovement, Supplier, SupplierMovement, User)


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(
        self,
        *,
        user_id: int | None,
        action: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = json.dumps(details, ensure_ascii=False) if details else None
        self._conn.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id, details_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, action, entity_type, entity_id, payload),
        )


_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
_SELECT = "SELECT u.*, r.code AS role_code FROM users u JOIN roles r ON r.id = u.role_id"


class UserRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            identifiant=row["identifiant"],
            nom=row["nom"],
            prenom=row["prenom"],
            role_id=row["role_id"],
            role_code=row["role_code"],
            is_active=bool(row["is_active"]),
            must_change_password=bool(row["must_change_password"]),
            failed_attempts=row["failed_attempts"],
            locked_until=row["locked_until"],
            last_login_at=row["last_login_at"],
            password_hash=row["password_hash"],
        )

    def get_by_id(self, user_id: int) -> User | None:
        row = self._conn.execute(f"{_SELECT} WHERE u.id = ?", (user_id,)).fetchone()
        return self._to_user(row) if row else None

    def get_by_identifiant(self, identifiant: str) -> User | None:
        row = self._conn.execute(f"{_SELECT} WHERE u.identifiant = ?", (identifiant,)).fetchone()
        return self._to_user(row) if row else None

    def list_all(self) -> list[User]:
        rows = self._conn.execute(f"{_SELECT} ORDER BY u.nom, u.prenom").fetchall()
        return [self._to_user(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def count_active_admins(self, exclude_user_id: int | None = None) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id "
            "WHERE r.code = 'ADMIN' AND u.is_active = 1 AND u.id != ?",
            (exclude_user_id if exclude_user_id is not None else -1,),
        ).fetchone()
        return int(row[0])

    def get_role_by_code(self, code: str) -> Role | None:
        row = self._conn.execute(
            "SELECT id, code, libelle FROM roles WHERE code = ?", (code,)
        ).fetchone()
        return Role(row["id"], row["code"], row["libelle"]) if row else None

    def list_roles(self) -> list[Role]:
        rows = self._conn.execute("SELECT id, code, libelle FROM roles ORDER BY id").fetchall()
        return [Role(r["id"], r["code"], r["libelle"]) for r in rows]

    def get_permission_codes(self, role_id: int) -> frozenset[str]:
        rows = self._conn.execute(
            "SELECT p.code FROM role_permissions rp "
            "JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = ?",
            (role_id,),
        ).fetchall()
        return frozenset(r["code"] for r in rows)

    def insert(
        self,
        *,
        identifiant: str,
        nom: str,
        prenom: str,
        password_hash: str,
        role_id: int,
        must_change_password: bool,
        created_by: int | None,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO users (identifiant, nom, prenom, password_hash, role_id, "
            "must_change_password, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                identifiant,
                nom,
                prenom,
                password_hash,
                role_id,
                int(must_change_password),
                created_by,
            ),
        )
        return int(cursor.lastrowid or 0)

    def update_profile(self, user_id: int, nom: str, prenom: str, role_id: int) -> None:
        self._conn.execute(
            f"UPDATE users SET nom = ?, prenom = ?, role_id = ?, updated_at = {_NOW} WHERE id = ?",
            (nom, prenom, role_id, user_id),
        )

    def set_password(self, user_id: int, password_hash: str, must_change: bool) -> None:
        self._conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ?, "
            f"failed_attempts = 0, locked_until = NULL, updated_at = {_NOW} WHERE id = ?",
            (password_hash, int(must_change), user_id),
        )

    def set_active(self, user_id: int, active: bool) -> None:
        self._conn.execute(
            "UPDATE users SET is_active = ?, failed_attempts = 0, locked_until = NULL, "
            f"updated_at = {_NOW} WHERE id = ?",
            (int(active), user_id),
        )

    def register_failed_attempt(
        self, user_id: int, attempts: int, locked_until: str | None
    ) -> None:
        self._conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, user_id),
        )

    def register_login(self, user_id: int, when_iso: str) -> None:
        self._conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? "
            "WHERE id = ?",
            (when_iso, user_id),
        )


# ----------------------------------------------------------------------------
# Paramètres, référentiels, produits, fournisseurs, lots, mouvements
# ----------------------------------------------------------------------------
def _like(term: str) -> str:
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SettingsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT valeur FROM app_settings WHERE cle = ?", (key,)).fetchone()
        return row["valeur"] if row else default
    
    def get_all(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT cle, valeur FROM app_settings"
        ).fetchall()
        return {r["cle"]: r["valeur"] for r in rows}

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_settings (cle, valeur) VALUES (?, ?) "
            "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
            (key, value),
        )



class ReferenceRepository:
    """Catégories et formes pharmaceutiques (même structure : id + nom)."""

    def __init__(self, conn: sqlite3.Connection, table: str) -> None:
        if table not in ("categories", "formes"):
            raise ValueError(table)
        self._conn = conn
        self._table = table

    def names(self) -> list[str]:
        rows = self._conn.execute(
            f"SELECT nom FROM {self._table} ORDER BY nom COLLATE NOCASE"
        ).fetchall()
        return [r["nom"] for r in rows]

    def get_or_create(self, nom: str) -> int:
        row = self._conn.execute(f"SELECT id FROM {self._table} WHERE nom = ?", (nom,)).fetchone()
        if row:
            return int(row["id"])
        cursor = self._conn.execute(f"INSERT INTO {self._table} (nom) VALUES (?)", (nom,))
        return int(cursor.lastrowid or 0)


_PRODUCT_SELECT = (
    "SELECT p.*, c.nom AS categorie FROM products p "
    "LEFT JOIN categories c ON c.id = p.categorie_id "
)


class ProductRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _to_product(row: sqlite3.Row) -> Product:
        return Product(
            id=row["id"],
            code=row["code"],
            code_barres=row["code_barres"],
            nom_commercial=row["nom_commercial"],
            description=row["description"],
            categorie_id=row["categorie_id"],
            categorie=row["categorie"],
            forme=row["forme"],
            dosage=row["dosage"],
            unite_vente=row["unite_vente"],
            sous_unite=row["sous_unite"],
            sous_unites_par_unite=row["sous_unites_par_unite"],
            prix_vente=row["prix_vente"],
            prix_vente_sous_unite=row["prix_vente_sous_unite"],
            seuil_minimal=row["seuil_minimal"],
            statut=row["statut"],
        )

    def list(self, search: str = "", statut: str | None = None) -> list[Product]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            clauses.append(
                "(p.code LIKE ? ESCAPE '\\' OR p.nom_commercial LIKE ? ESCAPE '\\' "
                "OR p.code_barres LIKE ? ESCAPE '\\' OR p.dosage LIKE ? ESCAPE '\\')"
            )
            params.extend([_like(search)] * 4)
        if statut:
            clauses.append("p.statut = ?")
            params.append(statut)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"{_PRODUCT_SELECT}{where} ORDER BY p.nom_commercial COLLATE NOCASE", params
        ).fetchall()
        return [self._to_product(r) for r in rows]

    def get(self, product_id: int) -> Product | None:
        row = self._conn.execute(f"{_PRODUCT_SELECT} WHERE p.id = ?", (product_id,)).fetchone()
        return self._to_product(row) if row else None

    def get_by_code(self, code: str) -> Product | None:
        row = self._conn.execute(f"{_PRODUCT_SELECT} WHERE p.code = ?", (code,)).fetchone()
        return self._to_product(row) if row else None

    def get_by_barcode(self, barcode: str) -> Product | None:
        row = self._conn.execute(
            f"{_PRODUCT_SELECT} WHERE p.code_barres = ?", (barcode,)
        ).fetchone()
        return self._to_product(row) if row else None

    def insert(self, values: dict[str, Any], created_by: int) -> int:
        data = {**values, "created_by": created_by}
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        cursor = self._conn.execute(
            f"INSERT INTO products ({columns}) VALUES ({marks})", tuple(data.values())
        )
        return int(cursor.lastrowid or 0)

    def update(self, product_id: int, values: dict[str, Any]) -> None:
        assignments = ", ".join(f"{column} = ?" for column in values)
        self._conn.execute(
            f"UPDATE products SET {assignments}, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (*values.values(), product_id),
        )

    def set_status(self, product_id: int, statut: str) -> None:
        self._conn.execute(
            "UPDATE products SET statut = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (statut, product_id),
        )

    def has_lots(self, product_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM lots WHERE product_id = ? LIMIT 1", (product_id,)
        ).fetchone()
        return row is not None
    
    def get_last_code(self, prefix: str, width: int) -> str | None:
        pattern = f"{prefix}-" + "?" * width

        row = self._conn.execute(
            """
            SELECT code
            FROM products
            WHERE code GLOB ?
            ORDER BY CAST(SUBSTR(code, ?) AS INTEGER) DESC
            LIMIT 1
            """,
            (pattern, len(prefix) + 2),
        ).fetchone()

        return row["code"] if row else None

class SupplierRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _to_supplier(row: sqlite3.Row) -> Supplier:
        return Supplier(
            id=row["id"],
            nom=row["nom"],
            telephone=row["telephone"],
            adresse=row["adresse"],
            statut=row["statut"],
        )

    def list(self, search: str = "", statut: str | None = None) -> list[Supplier]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            clauses.append(
                "(nom LIKE ? ESCAPE '\\' OR telephone LIKE ? ESCAPE '\\' "
                "OR adresse LIKE ? ESCAPE '\\')"
            )
            params.extend([_like(search)] * 3)
        if statut:
            clauses.append("statut = ?")
            params.append(statut)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM suppliers{where} ORDER BY nom COLLATE NOCASE", params
        ).fetchall()
        return [self._to_supplier(r) for r in rows]

    def get(self, supplier_id: int) -> Supplier | None:
        row = self._conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        return self._to_supplier(row) if row else None

    def get_by_name(self, nom: str) -> Supplier | None:
        row = self._conn.execute("SELECT * FROM suppliers WHERE nom = ?", (nom,)).fetchone()
        return self._to_supplier(row) if row else None

    def insert(self, nom: str, telephone: str | None, adresse: str | None, created_by: int) -> int:
        cursor = self._conn.execute(
            "INSERT INTO suppliers (nom, telephone, adresse, created_by) VALUES (?, ?, ?, ?)",
            (nom, telephone, adresse, created_by),
        )
        return int(cursor.lastrowid or 0)

    def update(
        self, supplier_id: int, nom: str, telephone: str | None, adresse: str | None
    ) -> None:
        self._conn.execute(
            "UPDATE suppliers SET nom = ?, telephone = ?, adresse = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (nom, telephone, adresse, supplier_id),
        )

    def set_status(self, supplier_id: int, statut: str) -> None:
        self._conn.execute(
            "UPDATE suppliers SET statut = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (statut, supplier_id),
        )


_LOT_SELECT = (
    "SELECT l.*, p.code AS product_code, p.nom_commercial AS product_nom, "
    "p.unite_vente AS product_unite_vente, p.sous_unite AS product_sous_unite, "
    "p.sous_unites_par_unite AS product_par_unite, s.nom AS supplier_nom "
    "FROM lots l JOIN products p ON p.id = l.product_id JOIN suppliers s ON s.id = l.supplier_id"
)


class LotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _to_lot(row: sqlite3.Row) -> Lot:
        return Lot(
            id=row["id"],
            product_id=row["product_id"],
            product_code=row["product_code"],
            product_nom=row["product_nom"],
            product_unite_vente=row["product_unite_vente"],
            product_sous_unite=row["product_sous_unite"],
            product_par_unite=row["product_par_unite"],
            supplier_id=row["supplier_id"],
            supplier_nom=row["supplier_nom"],
            numero_lot=row["numero_lot"],
            date_fabrication=row["date_fabrication"],
            date_peremption=row["date_peremption"],
            date_reception=row["date_reception"],
            quantite_recue=row["quantite_recue"],
            quantite_disponible=row["quantite_disponible"],
            prix_achat_total=row["prix_achat_total"],
            statut=row["statut"],
        )

    def list(
        self,
        search: str = "",
        product_id: int | None = None,
        supplier_id: int | None = None,
    ) -> list[Lot]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            clauses.append(
                "(p.nom_commercial LIKE ? ESCAPE '\\' OR p.code LIKE ? ESCAPE '\\' "
                "OR l.numero_lot LIKE ? ESCAPE '\\')"
            )
            params.extend([_like(search)] * 3)
        if product_id is not None:
            clauses.append("l.product_id = ?")
            params.append(product_id)
        if supplier_id is not None:
            clauses.append("l.supplier_id = ?")
            params.append(supplier_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"{_LOT_SELECT}{where} ORDER BY l.date_peremption, l.id", params
        ).fetchall()
        return [self._to_lot(r) for r in rows]

    def get(self, lot_id: int) -> Lot | None:
        row = self._conn.execute(f"{_LOT_SELECT} WHERE l.id = ?", (lot_id,)).fetchone()
        return self._to_lot(row) if row else None

    def list_sellable(self, product_id: int, today_iso: str) -> list[Lot]:
        """Lots vendables d'un produit dans l'ordre FEFO : actif, non périmé, en stock.
        Départage : péremption la plus proche, puis réception la plus ancienne, puis id."""
        rows = self._conn.execute(
            f"{_LOT_SELECT} WHERE l.product_id = ? AND l.statut = 'ACTIF' "
            "AND l.quantite_disponible > 0 AND l.date_peremption >= ? "
            "ORDER BY l.date_peremption, l.date_reception, l.id",
            (product_id, today_iso),
        ).fetchall()
        return [self._to_lot(r) for r in rows]

    def get_by_product_and_number(self, product_id: int, numero_lot: str) -> Lot | None:
        row = self._conn.execute(
            f"{_LOT_SELECT} WHERE l.product_id = ? AND l.numero_lot = ?",
            (product_id, numero_lot),
        ).fetchone()
        return self._to_lot(row) if row else None

    def insert(self, values: dict[str, Any], created_by: int) -> int:
        data = {**values, "created_by": created_by}
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        cursor = self._conn.execute(
            f"INSERT INTO lots ({columns}) VALUES ({marks})", tuple(data.values())
        )
        return int(cursor.lastrowid or 0)

    def add_received(self, lot_id: int, quantite_base: int, prix_achat_total: int = 0) -> None:
        """Cumule la quantité reçue ET le coût d'achat total d'un lot existant."""
        self._conn.execute(
            "UPDATE lots SET quantite_recue = quantite_recue + ?, "
            "prix_achat_total = prix_achat_total + ? WHERE id = ?",
            (quantite_base, prix_achat_total, lot_id),
        )

    def update(self, lot_id: int, values: dict[str, Any]) -> None:
        """Met à jour les champs descriptifs d'un lot (jamais le produit ni la quantité)."""
        allowed = {
            "numero_lot", "supplier_id", "date_fabrication", "date_peremption",
            "date_reception", "prix_achat_total",
        }
        data = {k: v for k, v in values.items() if k in allowed}
        if not data:
            return
        assignments = ", ".join(f"{column} = ?" for column in data)
        self._conn.execute(
            f"UPDATE lots SET {assignments} WHERE id = ?", (*data.values(), lot_id)
        )

    def has_exit_history(self, lot_id: int) -> bool:
        """Vrai si le lot a déjà un mouvement autre qu'une entrée (vente, retour, ajustement...)."""
        row = self._conn.execute(
            "SELECT 1 FROM stock_movements WHERE lot_id = ? "
            "AND type NOT IN ('STOCK_INITIAL', 'ENTREE_APPRO') LIMIT 1",
            (lot_id,),
        ).fetchone()
        return row is not None

    def set_status(self, lot_id: int, statut: str) -> None:
        self._conn.execute("UPDATE lots SET statut = ? WHERE id = ?", (statut, lot_id))


class MovementRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        type: str,  # noqa: A002
        product_id: int,
        lot_id: int,
        quantite_signee: int,
        user_id: int,
        motif: str | None = None,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> int:
        """Insère un mouvement ; le trigger met à jour la quantité du lot."""
        cursor = self._conn.execute(
            "INSERT INTO stock_movements "
            "(type, product_id, lot_id, quantite_signee, user_id, motif, ref_type, ref_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (type, product_id, lot_id, quantite_signee, user_id, motif, ref_type, ref_id),
        )
        return int(cursor.lastrowid or 0)

    def list_for_lot(self, lot_id: int) -> list[StockMovement]:
        rows = self._conn.execute(
            "SELECT m.*, u.prenom || ' ' || u.nom AS user_nom FROM stock_movements m "
            "JOIN users u ON u.id = m.user_id WHERE m.lot_id = ? ORDER BY m.id",
            (lot_id,),
        ).fetchall()
        return [
            StockMovement(
                id=r["id"],
                created_at=r["created_at"],
                type=r["type"],
                product_id=r["product_id"],
                lot_id=r["lot_id"],
                quantite_signee=r["quantite_signee"],
                user_id=r["user_id"],
                user_nom=r["user_nom"],
                motif=r["motif"],
                ref_type=r["ref_type"],
                ref_id=r["ref_id"],
            )
            for r in rows
        ]

    def list_for_supplier(self, supplier_id: int) -> list[SupplierMovement]:
        """Livraisons (réceptions de lots) fournies par ce fournisseur,
        du plus récent au plus ancien. Les ventes et autres mouvements sont exclus."""
        rows = self._conn.execute(
            """
            SELECT
                sm.id,
                sm.created_at,
                sm.type,
                sm.product_id,
                p.code             AS product_code,
                p.nom_commercial   AS product_nom,
                sm.lot_id,
                l.numero_lot       AS lot_numero,
                l.date_reception   AS lot_date_reception,
                l.date_peremption  AS lot_date_peremption,
                sm.quantite_signee,
                sm.user_id,
                (u.prenom || ' ' || u.nom) AS user_nom,
                sm.motif,
                sm.ref_type,
                sm.ref_id
            FROM stock_movements sm
            JOIN lots     l ON l.id = sm.lot_id
            JOIN products p ON p.id = sm.product_id
            JOIN users    u ON u.id = sm.user_id
            WHERE l.supplier_id = ?
              AND sm.type IN ('STOCK_INITIAL', 'ENTREE_APPRO')
            ORDER BY sm.created_at DESC, sm.id DESC
            """,
            (supplier_id,),
        ).fetchall()
        return [SupplierMovement(**dict(row)) for row in rows]

class SequenceRepository:
    """Numérotation unique et sans trou : à appeler DANS la transaction du document."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def next_number(self, doc_type: str, year: int) -> str:
        row = self._conn.execute(
            "SELECT prefixe, largeur, annee, prochain_numero FROM document_sequences "
            "WHERE type = ?",
            (doc_type,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Séquence inconnue : {doc_type}")

        number = row["prochain_numero"] if row["annee"] == year else 1

        self._conn.execute(
            "UPDATE document_sequences SET annee = ?, prochain_numero = ? WHERE type = ?",
            (year, number + 1, doc_type),
        )

        return f"{row['prefixe']}-{year}-{number:0{row['largeur']}d}"

class PaymentMethodRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _to_method(row: sqlite3.Row) -> PaymentMethod:
        return PaymentMethod(
            id=row["id"],
            code=row["code"],
            libelle=row["libelle"],
            is_cash=bool(row["is_cash"]),
        )

    def list_active(self) -> list[PaymentMethod]:
        rows = self._conn.execute(
            "SELECT * FROM payment_methods WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        return [self._to_method(r) for r in rows]

    def get_by_code(self, code: str) -> PaymentMethod | None:
        row = self._conn.execute(
            "SELECT * FROM payment_methods WHERE code = ? AND is_active = 1",
            (code,),
        ).fetchone()
        return self._to_method(row) if row else None


_SESSION_SELECT = (
    "SELECT c.*, (u.prenom || ' ' || u.nom) AS user_nom FROM cash_sessions c "
    "JOIN users u ON u.id = c.user_id"
)


class CashRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _to_session(row: sqlite3.Row) -> CashSession:
        return CashSession(
            id=row["id"],
            user_id=row["user_id"],
            user_nom=row["user_nom"],
            ouverte_le=row["ouverte_le"],
            fond_ouverture=row["fond_ouverture"],
            fermee_le=row["fermee_le"],
            montant_attendu=row["montant_attendu"],
            montant_compte=row["montant_compte"],
            ecart=row["ecart"],
            statut=row["statut"],
        )

    def get(self, session_id: int) -> CashSession | None:
        row = self._conn.execute(
            f"{_SESSION_SELECT} WHERE c.id = ?",
            (session_id,),
        ).fetchone()
        return self._to_session(row) if row else None

    def get_open(self, user_id: int) -> CashSession | None:
        row = self._conn.execute(
            f"{_SESSION_SELECT} WHERE c.user_id = ? AND c.statut = 'OUVERTE'",
            (user_id,),
        ).fetchone()
        return self._to_session(row) if row else None

    def insert(self, user_id: int, ouverte_le: str, fond: int) -> int:
        cursor = self._conn.execute(
            "INSERT INTO cash_sessions (user_id, ouverte_le, fond_ouverture) "
            "VALUES (?, ?, ?)",
            (user_id, ouverte_le, fond),
        )
        return int(cursor.lastrowid or 0)

    def close(
        self,
        session_id: int,
        when: str,
        attendu: int,
        compte: int,
        ecart: int,
    ) -> None:
        self._conn.execute(
            "UPDATE cash_sessions SET statut = 'CLOTUREE', fermee_le = ?, "
            "montant_attendu = ?, montant_compte = ?, ecart = ? WHERE id = ?",
            (when, attendu, compte, ecart, session_id),
        )

    def totals_by_method(self, session_id: int) -> list[dict[str, Any]]:
        """Encaissements nets (encaissements - remboursements) par moyen de paiement."""
        rows = self._conn.execute(
            "SELECT m.code, m.libelle, m.is_cash, "
            "SUM(CASE p.type WHEN 'ENCAISSEMENT' THEN p.montant "
            "ELSE -p.montant END) AS net "
            "FROM payments p JOIN payment_methods m "
            "ON m.id = p.payment_method_id "
            "WHERE p.cash_session_id = ? GROUP BY m.id ORDER BY m.id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def sales_count(self, session_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM sales "
            "WHERE cash_session_id = ? AND statut = 'VALIDEE'",
            (session_id,),
        ).fetchone()
        return int(row[0])


_SALE_SELECT = (
    "SELECT s.*, (u.prenom || ' ' || u.nom) AS user_nom, "
    "b.montant_paye, b.reste "
    "FROM sales s JOIN users u ON u.id = s.user_id "
    "JOIN v_sales_balance b ON b.sale_id = s.id"
)

_LINE_SELECT = (
    "SELECT sl.*, p.code AS product_code, "
    "p.nom_commercial AS product_nom, "
    "l.numero_lot AS numero_lot, "
    "l.date_peremption AS date_peremption, "
    "CASE sl.conditionnement WHEN 'SOUS_UNITE' "
    "THEN p.sous_unite ELSE p.unite_vente END AS unite "
    "FROM sale_lines sl "
    "JOIN products p ON p.id = sl.product_id "
    "JOIN lots l ON l.id = sl.lot_id"
)

_PAYMENT_SELECT = (
    "SELECT p.*, m.code AS method_code, m.libelle AS method_libelle, "
    "(u.prenom || ' ' || u.nom) AS user_nom "
    "FROM payments p "
    "JOIN payment_methods m ON m.id = p.payment_method_id "
    "JOIN users u ON u.id = p.user_id"
)


class SaleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- conversions ---------------------------------------------------------------

    @staticmethod
    def _to_sale(row: sqlite3.Row) -> Sale:
        return Sale(
            id=row["id"],
            numero_vente=row["numero_vente"],
            date_vente=row["date_vente"],
            user_id=row["user_id"],
            user_nom=row["user_nom"],
            cash_session_id=row["cash_session_id"],
            client_nom=row["client_nom"],
            client_telephone=row["client_telephone"],
            montant_brut=row["montant_brut"],
            remise_globale=row["remise_globale"],
            taux_taxe_bp=row["taux_taxe_bp"],
            taxes=row["taxes"],
            montant_net=row["montant_net"],
            statut=row["statut"],
            annulee_le=row["annulee_le"],
            motif_annulation=row["motif_annulation"],
            montant_paye=row["montant_paye"],
            reste=row["reste"],
        )

    @staticmethod
    def _to_line(row: sqlite3.Row) -> SaleLine:
        return SaleLine(
            id=row["id"],
            sale_id=row["sale_id"],
            product_id=row["product_id"],
            product_code=row["product_code"],
            product_nom=row["product_nom"],
            lot_id=row["lot_id"],
            numero_lot=row["numero_lot"],
            conditionnement=row["conditionnement"],
            unite=row["unite"],
            quantite=row["quantite"],
            quantite_base=row["quantite_base"],
            prix_unitaire=row["prix_unitaire"],
            cout_total=row["cout_total"],
            remise=row["remise"],
            montant_ligne=row["montant_ligne"],
            date_peremption=row["date_peremption"],
        )

    @staticmethod
    def _to_payment(row: sqlite3.Row) -> Payment:
        return Payment(
            id=row["id"],
            reference=row["reference"],
            sale_id=row["sale_id"],
            method_code=row["method_code"],
            method_libelle=row["method_libelle"],
            cash_session_id=row["cash_session_id"],
            type=row["type"],
            montant=row["montant"],
            date_paiement=row["date_paiement"],
            user_id=row["user_id"],
            user_nom=row["user_nom"],
            note=row["note"],
        )

    # --- ventes --------------------------------------------------------------------

    def insert_sale(self, values: dict[str, Any]) -> int:
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cursor = self._conn.execute(
            f"INSERT INTO sales ({columns}) VALUES ({marks})",
            tuple(values.values()),
        )
        return int(cursor.lastrowid or 0)

    def insert_line(self, values: dict[str, Any]) -> int:
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cursor = self._conn.execute(
            f"INSERT INTO sale_lines ({columns}) VALUES ({marks})",
            tuple(values.values()),
        )
        return int(cursor.lastrowid or 0)

    def get(self, sale_id: int) -> Sale | None:
        row = self._conn.execute(
            f"{_SALE_SELECT} WHERE s.id = ?",
            (sale_id,),
        ).fetchone()
        return self._to_sale(row) if row else None

    def get_by_token(self, token: str) -> Sale | None:
        row = self._conn.execute(
            f"{_SALE_SELECT} WHERE s.token_idempotence = ?",
            (token,),
        ).fetchone()
        return self._to_sale(row) if row else None

    def list(
        self,
        start_iso: str,
        end_iso: str,
        user_id: int | None = None,
        limit: int | None = None,
    ) -> list[Sale]:
        sql = f"{_SALE_SELECT} WHERE s.date_vente >= ? AND s.date_vente < ?"
        params: list[Any] = [start_iso, end_iso]

        if user_id is not None:
            sql += " AND s.user_id = ?"
            params.append(user_id)

        sql += " ORDER BY s.id DESC"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        return [
            self._to_sale(r)
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def lines(self, sale_id: int) -> list[SaleLine]:
        rows = self._conn.execute(
            f"{_LINE_SELECT} WHERE sl.sale_id = ? ORDER BY sl.id",
            (sale_id,),
        )
        return [self._to_line(r) for r in rows.fetchall()]

    def mark_cancelled(
        self,
        sale_id: int,
        when: str,
        by: int,
        motif: str,
    ) -> None:
        self._conn.execute(
            "UPDATE sales SET statut = 'ANNULEE', annulee_le = ?, "
            "annulee_par = ?, motif_annulation = ? WHERE id = ?",
            (when, by, motif, sale_id),
        )

    # --- paiements -----------------------------------------------------------------

    def insert_payment(self, values: dict[str, Any]) -> int:
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cursor = self._conn.execute(
            f"INSERT INTO payments ({columns}) VALUES ({marks})",
            tuple(values.values()),
        )
        return int(cursor.lastrowid or 0)

    def payments(self, sale_id: int) -> list[Payment]:
        rows = self._conn.execute(
            f"{_PAYMENT_SELECT} WHERE p.sale_id = ? ORDER BY p.id",
            (sale_id,),
        ).fetchall()
        return [self._to_payment(r) for r in rows]

    def net_paid_by_method(self, sale_id: int) -> list[tuple[int, int]]:
        """(payment_method_id, net encaissé) pour chaque moyen encore créditeur."""
        rows = self._conn.execute(
            "SELECT payment_method_id, "
            "SUM(CASE type WHEN 'ENCAISSEMENT' THEN montant "
            "ELSE -montant END) AS net "
            "FROM payments WHERE sale_id = ? "
            "GROUP BY payment_method_id HAVING net > 0",
            (sale_id,),
        ).fetchall()
        return [(r["payment_method_id"], r["net"]) for r in rows]

    # --- factures ------------------------------------------------------------------

    @staticmethod
    def _to_invoice(row: sqlite3.Row) -> Invoice:
        return Invoice(
            id=row["id"],
            numero_facture=row["numero_facture"],
            sale_id=row["sale_id"],
            emise_le=row["emise_le"],
            emise_par=row["emise_par"],
            client_nom=row["client_nom"],
            client_telephone=row["client_telephone"],
            chemin_pdf=row["chemin_pdf"],
        )

    def invoice_for_sale(self, sale_id: int) -> Invoice | None:
        row = self._conn.execute(
            "SELECT * FROM invoices WHERE sale_id = ?",
            (sale_id,),
        ).fetchone()
        return self._to_invoice(row) if row else None

    def insert_invoice(
        self,
        numero: str,
        sale_id: int,
        emise_le: str,
        emise_par: int,
        client_nom: str | None,
        client_telephone: str | None,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO invoices (numero_facture, sale_id, emise_le, emise_par, "
            "client_nom, client_telephone) VALUES (?, ?, ?, ?, ?, ?)",
            (numero, sale_id, emise_le, emise_par, client_nom, client_telephone),
        )
        return int(cursor.lastrowid or 0)

    def set_invoice_pdf(self, invoice_id: int, path: str) -> None:
        self._conn.execute(
            "UPDATE invoices SET chemin_pdf = ? WHERE id = ?",
            (path, invoice_id),
        )


class StatsRepository:
    """Indicateurs du tableau de bord (lecture seule)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def active_products(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM products WHERE statut = 'ACTIF'"
        ).fetchone()
        return int(row[0])

    def stock_value(self) -> int:
        """Valeur du stock au coût d'achat (lots en stock, périmés compris)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM((prix_achat_total * quantite_disponible "
            "+ quantite_recue / 2) / quantite_recue), 0) "
            "FROM lots WHERE quantite_disponible > 0"
        ).fetchone()
        return int(row[0])


    def sales_totals(
        self,
        start_iso: str,
        end_iso: str,
        user_id: int | None = None,
    ) -> tuple[int, int]:
        """(nombre de ventes validées, chiffre d'affaires net) sur la période."""
        sql = (
            "SELECT COUNT(*), COALESCE(SUM(montant_net), 0) FROM sales "
            "WHERE statut = 'VALIDEE' AND date_vente >= ? AND date_vente < ?"
        )
        params: list[Any] = [start_iso, end_iso]

        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)

        row = self._conn.execute(sql, params).fetchone()
        return int(row[0]), int(row[1])

    def receivables(self) -> tuple[int, int]:
        """(nombre de ventes avec solde, montant total des créances)."""
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(b.reste), 0) "
            "FROM v_sales_balance b "
            "JOIN sales s ON s.id = b.sale_id "
            "WHERE s.statut = 'VALIDEE' AND b.reste > 0"
        ).fetchone()
        return int(row[0]), int(row[1])

    def product_stock(self, today_iso: str) -> list[sqlite3.Row]:
        """Stock vendable (lots actifs, non périmés) de chaque produit actif."""
        return self._conn.execute(
            "SELECT p.id, p.code, p.nom_commercial, p.seuil_minimal, "
            "p.unite_vente, p.sous_unite, p.sous_unites_par_unite, "
            "COALESCE(SUM(CASE WHEN l.statut = 'ACTIF' "
            "AND l.date_peremption >= ? "
            "THEN l.quantite_disponible END), 0) AS stock "
            "FROM products p LEFT JOIN lots l ON l.product_id = p.id "
            "WHERE p.statut = 'ACTIF' "
            "GROUP BY p.id ORDER BY p.nom_commercial COLLATE NOCASE",
            (today_iso,),
        ).fetchall()

    def stock_for_products(
        self,
        product_ids: list[int],
        today_iso: str,
    ) -> dict[int, int]:
        """Stock vendable (unité de base) pour une liste de produits."""
        result: dict[int, int] = {}
        # Par paquets : SQLite limite le nombre de paramètres d'une requête.
        for start in range(0, len(product_ids), 500):
            chunk = product_ids[start:start + 500]
            marks = ", ".join("?" for _ in chunk)
            rows = self._conn.execute(
                f"SELECT product_id, SUM(quantite_disponible) AS stock FROM lots "
                f"WHERE product_id IN ({marks}) AND statut = 'ACTIF' "
                "AND date_peremption >= ? "
                "GROUP BY product_id",
                (*chunk, today_iso),
            ).fetchall()
            result.update({r["product_id"]: int(r["stock"]) for r in rows})
        return result
