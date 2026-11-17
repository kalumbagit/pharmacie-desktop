-- Étape 4 v2 — schéma cible après intégration des énums et du prix d'achat total.
-- Convention : montants en FCFA (entiers), dates ISO, quantités en UNITÉ DE BASE
-- (la sous-unité si le produit en a une, sinon l'unité de vente).
--
-- ⚠️ Les colonnes `forme` et `unite_vente` sont contraintes par CHECK pour refléter
--     les énumérations de `app/core/enums.py` (Forme, UniteVente). Toute évolution
--     de l'énumération doit être répercutée dans le CHECK (test unitaire recommandé).

-- ─────────────────────────────────────────────────────────────────────────────
-- Référentiel conservé : catégories (évolutif, utilisé en reporting)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL UNIQUE COLLATE NOCASE
);

INSERT INTO
    categories (nom)
VALUES (
        'Antalgiques et antipyrétiques'
    ),
    ('Antibiotiques'),
    ('Antipaludiques'),
    ('Antihypertenseurs'),
    ('Antidiabétiques'),
    ('Vitamines et compléments'),
    ('Soins et hygiène'),
    ('Matériel médical'),
    ('Autres');

-- ─────────────────────────────────────────────────────────────────────────────
-- Produits
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    code_barres TEXT UNIQUE,
    nom_commercial TEXT NOT NULL,
    description TEXT,
    categorie_id INTEGER REFERENCES categories (id),

-- Forme galénique : texte libre contraint à l'énumération Forme
forme TEXT CHECK (
    forme IS NULL
    OR forme IN (
        'Comprimé',
        'Gélule',
        'Poudre',
        'Sirop',
        'Solution buvable',
        'Suspension',
        'Pommade',
        'Crème',
        'Gel',
        'Suppositoire',
        'Ampoule',
        'Collyre',
        'Gouttes',
        'Injectable',
        'Spray',
        'Patch',
        'Ovule',
        'Autre'
    )
),
dosage TEXT,

-- Unité de vente : texte contraint à l'énumération UniteVente
unite_vente TEXT NOT NULL DEFAULT 'Boîte' CHECK (
    unite_vente IN (
        'Boîte',
        'Flacon',
        'Tube',
        'Sachet',
        'Ampoule',
        'Plaquette',
        'Comprimé',
        'Gélule',
        'Unité',
        'Bidon',
        'Pot',
        'Spray',
        'Autre'
    )
),

-- Sous-unité : QComboBox éditable côté UI → texte libre (pas de CHECK)
sous_unite TEXT,
sous_unites_par_unite INTEGER NOT NULL DEFAULT 1 CHECK (sous_unites_par_unite >= 1),

-- Prix de vente (unité de vente)
prix_vente INTEGER NOT NULL DEFAULT 0 CHECK (prix_vente >= 0),
-- Prix de vente (sous-unité) si applicable
prix_vente_sous_unite INTEGER CHECK (
    prix_vente_sous_unite IS NULL
    OR prix_vente_sous_unite >= 0
),
seuil_minimal INTEGER NOT NULL DEFAULT 0 CHECK (seuil_minimal >= 0),
statut TEXT NOT NULL DEFAULT 'ACTIF' CHECK (
    statut IN ('ACTIF', 'INACTIF')
),
created_at TEXT NOT NULL DEFAULT(
    strftime ('%Y-%m-%dT%H:%M:%SZ', 'now')
),
created_by INTEGER REFERENCES users (id),
updated_at TEXT,

-- Cohérence conditionnement ↔ sous-unité
CHECK (
        (sous_unite IS NULL
         AND sous_unites_par_unite = 1
         AND prix_vente_sous_unite IS NULL)
        OR
        (sous_unite IS NOT NULL
         AND sous_unites_par_unite >= 2
         AND prix_vente_sous_unite IS NOT NULL)
    )
);

CREATE INDEX idx_products_nom ON products (nom_commercial);

-- ─────────────────────────────────────────────────────────────────────────────
-- Fournisseurs
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL UNIQUE COLLATE NOCASE,
    telephone TEXT,
    adresse TEXT,
    statut TEXT NOT NULL DEFAULT 'ACTIF' CHECK (
        statut IN ('ACTIF', 'INACTIF')
    ),
    created_at TEXT NOT NULL DEFAULT(
        strftime ('%Y-%m-%dT%H:%M:%SZ', 'now')
    ),
    created_by INTEGER REFERENCES users (id),
    updated_at TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Lots
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products (id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    numero_lot TEXT NOT NULL,
    date_fabrication TEXT CHECK (
        date_fabrication IS NULL
        OR date_fabrication GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    date_peremption TEXT NOT NULL CHECK (
        date_peremption GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    date_reception TEXT NOT NULL CHECK (
        date_reception GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    quantite_recue INTEGER NOT NULL CHECK (quantite_recue > 0),
    quantite_disponible INTEGER NOT NULL DEFAULT 0
        CHECK (quantite_disponible >= 0),

-- Coût d'achat TOTAL du lot (cumulé à chaque réception complémentaire)

prix_achat_total INTEGER NOT NULL DEFAULT 0
        CHECK (prix_achat_total >= 0),

    statut TEXT NOT NULL DEFAULT 'ACTIF'
        CHECK (statut IN ('ACTIF', 'BLOQUE')),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    ),
    created_by INTEGER REFERENCES users (id),
    UNIQUE (product_id, numero_lot),
    CHECK (
        date_fabrication IS NULL
        OR date_fabrication <= date_peremption
    )
);

CREATE INDEX idx_lots_product_peremption ON lots (product_id, date_peremption);

CREATE INDEX idx_lots_supplier ON lots (supplier_id);

CREATE INDEX idx_lots_peremption ON lots (date_peremption);

-- ─────────────────────────────────────────────────────────────────────────────
-- Mouvements de stock (immuables, source de vérité des quantités)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT(
        strftime ('%Y-%m-%dT%H:%M:%SZ', 'now')
    ),
    type TEXT NOT NULL CHECK (
        type IN (
            'STOCK_INITIAL',
            'ENTREE_APPRO',
            'VENTE',
            'ANNULATION_VENTE',
            'RETOUR_CLIENT',
            'RETOUR_FOURNISSEUR',
            'AJUSTEMENT_POSITIF',
            'AJUSTEMENT_NEGATIF',
            'INVENTAIRE',
            'PEREMPTION',
            'CASSE'
        )
    ),
    product_id INTEGER NOT NULL REFERENCES products (id),
    lot_id INTEGER NOT NULL REFERENCES lots (id),
    quantite_signee INTEGER NOT NULL CHECK (quantite_signee != 0),
    user_id INTEGER NOT NULL REFERENCES users (id),
    motif TEXT,
    ref_type TEXT,
    ref_id INTEGER
);

CREATE INDEX idx_movements_lot ON stock_movements (lot_id);

CREATE INDEX idx_movements_product ON stock_movements (product_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Triggers (inchangés)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TRIGGER stock_movements_check_product
BEFORE INSERT ON stock_movements
WHEN (SELECT product_id FROM lots WHERE id = NEW.lot_id) IS NOT NEW.product_id
BEGIN
    SELECT RAISE(ABORT, 'Le produit du mouvement ne correspond pas au lot');
END;

CREATE TRIGGER stock_movements_apply
AFTER INSERT ON stock_movements
BEGIN
    UPDATE lots
    SET quantite_disponible = quantite_disponible + NEW.quantite_signee
    WHERE id = NEW.lot_id;
END;

CREATE TRIGGER lots_quantity_only_via_movements
BEFORE UPDATE OF quantite_disponible ON lots
WHEN NEW.quantite_disponible != COALESCE(
    (SELECT SUM(quantite_signee) FROM stock_movements WHERE lot_id = OLD.id), 0
)
BEGIN
    SELECT RAISE(ABORT, 'La quantité d''un lot ne change que par un mouvement de stock');
END;

CREATE TRIGGER stock_movements_no_update
BEFORE UPDATE ON stock_movements
BEGIN SELECT RAISE(ABORT, 'stock_movements est immuable'); END;

CREATE TRIGGER stock_movements_no_delete
BEFORE DELETE ON stock_movements
BEGIN SELECT RAISE(ABORT, 'stock_movements est immuable'); END;

CREATE TRIGGER products_no_delete
BEFORE DELETE ON products
BEGIN SELECT RAISE(ABORT, 'Un produit ne peut pas être supprimé, désactivez-le'); END;

CREATE TRIGGER suppliers_no_delete
BEFORE DELETE ON suppliers
BEGIN SELECT RAISE(ABORT, 'Un fournisseur ne peut pas être supprimé, désactivez-le'); END;

CREATE TRIGGER lots_no_delete
BEFORE DELETE ON lots
BEGIN SELECT RAISE(ABORT, 'Un lot ne peut pas être supprimé, bloquez-le'); END;

CREATE TRIGGER lots_product_immutable
BEFORE UPDATE OF product_id ON lots
WHEN NEW.product_id != OLD.product_id
BEGIN SELECT RAISE(ABORT, 'Le produit d''un lot ne peut pas changer'); END;

CREATE TRIGGER products_packaging_locked
BEFORE UPDATE OF sous_unite, sous_unites_par_unite ON products
WHEN EXISTS (SELECT 1 FROM lots WHERE product_id = OLD.id)
 AND (OLD.sous_unite IS NOT NEW.sous_unite
      OR OLD.sous_unites_par_unite != NEW.sous_unites_par_unite)
BEGIN SELECT RAISE(ABORT, 'Le conditionnement ne peut plus changer : le produit a des lots'); END;

-- ─────────────────────────────────────────────────────────────────────────────
-- Paramètres
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO
    app_settings (cle, valeur)
VALUES (
        'peremption_alerte_jours',
        '90'
    );