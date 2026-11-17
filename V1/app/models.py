"""Modèles de données (dataclasses). Aucun code d'interface ni de SQL ici.

Champs liés aux énumérations (après migration 0004 — énums à la place des tables) :

* `Product.forme`       → valeur textuelle de `app.core.enums.Forme`
                          (colonne `products.forme TEXT`, plus de FK `forme_id`)
* `Product.unite_vente` → valeur textuelle de `app.core.enums.UniteVente`
* `Product.sous_unite`  → valeur textuelle de `app.core.enums.SousUnite`
                          (tolérant au texte libre : l'utilisateur peut saisir
                          une valeur hors liste via le QComboBox éditable)
* `Product.categorie`   → libellé dénormalisé depuis la table `categories`
                          (qui reste une table de référence gérée)
* `Lot.prix_achat_total`    → montant total payé pour le lot (entier)
* `Lot.prix_achat_unitaire` → propriété calculée (float) = total / quantité

Aucune référence aux anciennes tables `formes` / `unites_vente` : elles ont été
supprimées par la migration 0004.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.enums import Forme, SousUnite, UniteVente


@dataclass(frozen=True)
class Role:
    id: int
    code: str
    libelle: str


@dataclass(frozen=True)
class User:
    id: int
    identifiant: str
    nom: str
    prenom: str
    role_id: int
    role_code: str
    is_active: bool
    must_change_password: bool
    failed_attempts: int
    locked_until: str | None
    last_login_at: str | None
    password_hash: str = field(default="", repr=False)

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}".strip()


# ----------------------------------------------------------------------------
# Produits, fournisseurs, lots, mouvements
# ----------------------------------------------------------------------------
def format_quantity(
    quantite_base: int, unite_vente: str, sous_unite: str | None, par_unite: int
) -> str:
    """Affiche une quantité en unité de base, ex. 14 -> « 4 Boîte + 2 Plaquette »."""
    if not sous_unite:
        return f"{quantite_base} {unite_vente}"
    unites, reste = divmod(quantite_base, par_unite)
    parts = []
    if unites or not reste:
        parts.append(f"{unites} {unite_vente}")
    if reste:
        parts.append(f"{reste} {sous_unite}")
    return " + ".join(parts)


@dataclass(frozen=True)
class Product:
    id: int
    code: str
    code_barres: str | None
    nom_commercial: str
    description: str | None
    categorie_id: int | None       # FK vers `categories` (table conservée)
    categorie: str | None          # libellé joint (dénormalisé)
    forme: str | None              # texte issu de `Forme.values()`, ou None
    dosage: str | None
    unite_vente: str               # texte issu de `UniteVente.values()`
    sous_unite: str | None         # texte issu de `SousUnite.values()` (ou libre)
    sous_unites_par_unite: int
    prix_vente: int
    prix_vente_sous_unite: int | None
    seuil_minimal: int             # en unité de base
    statut: str

    @property
    def is_active(self) -> bool:
        return self.statut == "ACTIF"

    @property
    def has_sous_unite(self) -> bool:
        return self.sous_unite is not None

    @property
    def unite_base(self) -> str:
        return self.sous_unite or self.unite_vente

    # --- accès typés aux énumérations ----------------------------------------
    @property
    def forme_enum(self) -> "Forme | None":
        """Forme typée (`Forme`), ou `None` si aucune forme renseignée.

        Lève `ValueError` si la valeur stockée sort de l'énumération (cas
        anormal après la migration, mais possible en cas d'INSERT direct).
        """
        from app.core.enums import Forme
        return Forme(self.forme) if self.forme else None

    @property
    def unite_vente_enum(self) -> "UniteVente":
        """Unité de vente typée. Lève `ValueError` si la valeur stockée est invalide."""
        from app.core.enums import UniteVente
        return UniteVente(self.unite_vente)

    @property
    def sous_unite_enum(self) -> "SousUnite | None":
        """Sous-unité typée, ou `None` si vide ou saisie hors énumération (texte libre)."""
        from app.core.enums import SousUnite
        if not self.sous_unite:
            return None
        try:
            return SousUnite(self.sous_unite)
        except ValueError:
            return None

    def to_base(self, quantite: int, conditionnement: str = "UNITE") -> int:
        """Convertit une quantité saisie (« UNITE » ou « SOUS_UNITE ») en unité de base."""
        if conditionnement == "SOUS_UNITE":
            if not self.has_sous_unite:
                raise ValueError("Ce produit n'a pas de sous-unité.")
            return quantite
        return quantite * self.sous_unites_par_unite

    def format_quantity(self, quantite_base: int) -> str:
        return format_quantity(
            quantite_base, self.unite_vente, self.sous_unite, self.sous_unites_par_unite
        )


@dataclass(frozen=True)
class Supplier:
    id: int
    nom: str
    telephone: str | None
    adresse: str | None
    statut: str

    @property
    def is_active(self) -> bool:
        return self.statut == "ACTIF"


LOT_ETATS = {
    "OK": "Disponible",
    "PROCHE": "Péremption proche",
    "EXPIRE": "Périmé",
    "BLOQUE": "Bloqué",
    "EPUISE": "Épuisé",
}


@dataclass(frozen=True)
class Lot:
    id: int
    product_id: int
    product_code: str
    product_nom: str
    product_unite_vente: str
    product_sous_unite: str | None
    product_par_unite: int
    supplier_id: int
    supplier_nom: str
    numero_lot: str
    date_fabrication: str | None
    date_peremption: str
    date_reception: str
    quantite_recue: int
    quantite_disponible: int
    prix_achat_total: int          # prix d'achat total du lot (entier)
    statut: str
    etat: str = ""                 # calculé par le service (voir LOT_ETATS)

    @property
    def prix_achat_unitaire(self) -> float:
        """Prix d'achat moyen par unité de base, calculé à partir du total."""
        if self.quantite_recue <= 0:
            return 0.0
        return self.prix_achat_total / self.quantite_recue

    def format_quantity(self, quantite_base: int) -> str:
        return format_quantity(
            quantite_base,
            self.product_unite_vente,
            self.product_sous_unite,
            self.product_par_unite,
        )


MOVEMENT_LABELS = {
    "STOCK_INITIAL": "Stock initial",
    "ENTREE_APPRO": "Entrée (approvisionnement)",
    "VENTE": "Vente",
    "ANNULATION_VENTE": "Annulation de vente",
    "RETOUR_CLIENT": "Retour client",
    "RETOUR_FOURNISSEUR": "Retour fournisseur",
    "AJUSTEMENT_POSITIF": "Ajustement (+)",
    "AJUSTEMENT_NEGATIF": "Ajustement (-)",
    "INVENTAIRE": "Inventaire",
    "PEREMPTION": "Produit périmé",
    "CASSE": "Produit endommagé",
}


@dataclass(frozen=True)
class StockMovement:
    id: int
    created_at: str
    type: str
    product_id: int
    lot_id: int
    quantite_signee: int
    user_id: int
    user_nom: str
    motif: str | None
    ref_type: str | None
    ref_id: int | None


@dataclass(frozen=True)
class SupplierMovement:
    """Mouvement de stock enrichi avec lot + produit + utilisateur.

    Utilisé par la page « Historique fournisseur » : permet de lister toutes les
    transactions liées aux lots fournis par un fournisseur donné (réceptions,
    retours fournisseur, sorties exceptionnelles…).
    """
    id: int
    created_at: str
    type: str
    product_id: int
    product_code: str
    product_nom: str
    lot_id: int
    lot_numero: str
    lot_date_reception: str
    lot_date_peremption: str
    quantite_signee: int
    user_id: int
    user_nom: str
    motif: str | None
    ref_type: str | None
    ref_id: int | None



# ----------------------------------------------------------------------------
# Caisse, ventes, paiements, factures
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class PaymentMethod:
    id: int
    code: str
    libelle: str
    is_cash: bool


@dataclass(frozen=True)
class CashSession:
    id: int
    user_id: int
    user_nom: str
    ouverte_le: str
    fond_ouverture: int
    fermee_le: str | None
    montant_attendu: int | None
    montant_compte: int | None
    ecart: int | None
    statut: str

    @property
    def is_open(self) -> bool:
        return self.statut == "OUVERTE"


@dataclass(frozen=True)
class Sale:
    id: int
    numero_vente: str
    date_vente: str
    user_id: int
    user_nom: str
    cash_session_id: int
    client_nom: str | None
    client_telephone: str | None
    montant_brut: int
    remise_globale: int
    taux_taxe_bp: int
    taxes: int
    montant_net: int
    statut: str
    annulee_le: str | None
    motif_annulation: str | None
    montant_paye: int
    reste: int

    @property
    def is_cancelled(self) -> bool:
        return self.statut == "ANNULEE"


@dataclass(frozen=True)
class SaleLine:
    id: int
    sale_id: int
    product_id: int
    product_code: str
    product_nom: str
    lot_id: int
    numero_lot: str
    conditionnement: str
    unite: str
    quantite: int
    quantite_base: int
    prix_unitaire: int
    cout_total: int
    remise: int
    montant_ligne: int
    date_peremption: str | None = None


@dataclass(frozen=True)
class Payment:
    id: int
    reference: str
    sale_id: int
    method_code: str
    method_libelle: str
    cash_session_id: int
    type: str
    montant: int
    date_paiement: str
    user_id: int
    user_nom: str
    note: str | None


@dataclass(frozen=True)
class Invoice:
    id: int
    numero_facture: str
    sale_id: int
    emise_le: str
    emise_par: int
    client_nom: str | None
    client_telephone: str | None
    chemin_pdf: str | None