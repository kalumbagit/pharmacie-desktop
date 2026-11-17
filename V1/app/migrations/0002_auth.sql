CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    libelle TEXT NOT NULL
);

CREATE TABLE permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    libelle TEXT NOT NULL
);

CREATE TABLE role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles (id),
    permission_id INTEGER NOT NULL REFERENCES permissions (id),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifiant TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nom TEXT NOT NULL,
    prenom TEXT,
    password_hash TEXT NOT NULL,
    role_id INTEGER NOT NULL REFERENCES roles (id),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (
        must_change_password IN (0, 1)
    ),
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT(
        strftime ('%Y-%m-%dT%H:%M:%SZ', 'now')
    ),
    created_by INTEGER REFERENCES users (id),
    updated_at TEXT
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT(
        strftime ('%Y-%m-%dT%H:%M:%SZ', 'now')
    ),
    user_id INTEGER REFERENCES users (id),
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    details_json TEXT
);

CREATE INDEX idx_audit_log_created_at ON audit_log (created_at);

CREATE INDEX idx_audit_log_user ON audit_log (user_id);

-- Journal d'audit immuable, utilisateurs jamais supprimés
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log est immuable'); END;

CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log est immuable'); END;

CREATE TRIGGER users_no_delete BEFORE DELETE ON users
BEGIN SELECT RAISE(ABORT, 'Un utilisateur ne peut pas être supprimé, désactivez-le'); END;

-- Rôles
INSERT INTO
    roles (code, libelle)
VALUES ('ADMIN', 'Administrateur'),
    ('PHARMACIEN', 'Pharmacien'),
    ('CAISSIER', 'Caissier');

-- Permissions
INSERT INTO
    permissions (code, libelle)
VALUES (
        'users.manage',
        'Gérer les utilisateurs'
    ),
    (
        'settings.edit',
        'Configurer l''application'
    ),
    (
        'backup.manage',
        'Sauvegarder et restaurer la base'
    ),
    (
        'audit.view',
        'Consulter le journal d''audit'
    ),
    (
        'products.view',
        'Consulter les produits'
    ),
    (
        'products.edit',
        'Créer et modifier les produits'
    ),
    (
        'price.edit',
        'Modifier les prix de vente'
    ),
    (
        'lots.view',
        'Consulter les lots et péremptions'
    ),
    (
        'suppliers.view',
        'Consulter les fournisseurs'
    ),
    (
        'suppliers.edit',
        'Gérer les fournisseurs'
    ),
    (
        'purchases.view',
        'Consulter les approvisionnements'
    ),
    (
        'purchases.create',
        'Enregistrer des approvisionnements'
    ),
    (
        'purchases.pay',
        'Régler les fournisseurs'
    ),
    (
        'stock.view',
        'Consulter les stocks'
    ),
    (
        'stock.adjust',
        'Ajuster le stock, périmés, endommagés'
    ),
    (
        'inventory.run',
        'Réaliser des inventaires'
    ),
    (
        'sales.create',
        'Effectuer des ventes'
    ),
    (
        'sales.view_own',
        'Consulter ses propres ventes'
    ),
    (
        'sales.view_all',
        'Consulter toutes les ventes'
    ),
    (
        'sales.discount',
        'Appliquer des remises'
    ),
    (
        'sales.cancel',
        'Annuler des ventes'
    ),
    (
        'payments.record',
        'Enregistrer des paiements'
    ),
    (
        'cash.session',
        'Ouvrir et clôturer une session de caisse'
    ),
    (
        'invoices.generate',
        'Générer factures et reçus'
    ),
    (
        'returns.create',
        'Enregistrer des retours'
    ),
    (
        'expenses.edit',
        'Gérer les dépenses'
    ),
    (
        'accounting.view',
        'Consulter la comptabilité'
    ),
    (
        'reports.financial',
        'Consulter les rapports financiers'
    ),
    (
        'reports.stock',
        'Consulter les rapports de stock'
    );

-- Administrateur : toutes les permissions
INSERT INTO
    role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
    CROSS JOIN permissions p
WHERE
    r.code = 'ADMIN';

-- Pharmacien
INSERT INTO
    role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
    JOIN permissions p ON p.code IN (
        'products.view', 'lots.view', 'suppliers.view', 'purchases.view', 'purchases.create', 'stock.view', 'stock.adjust', 'inventory.run', 'sales.create', 'sales.view_own', 'sales.view_all', 'sales.discount', 'sales.cancel', 'payments.record', 'cash.session', 'invoices.generate', 'returns.create', 'reports.stock'
    )
WHERE
    r.code = 'PHARMACIEN';

-- Caissier
INSERT INTO
    role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
    JOIN permissions p ON p.code IN (
        'products.view', 'sales.create', 'sales.view_own', 'sales.discount', 'payments.record', 'cash.session', 'invoices.generate'
    )
WHERE
    r.code = 'CAISSIER';