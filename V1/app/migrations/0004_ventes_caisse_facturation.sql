-- Étape 6 : ventes, caisse, paiements, factures, numérotation.
-- Conventions : montants en FCFA (entiers), quantités en unité de base,
-- dates ISO UTC.
-- Aucune suppression : une vente se corrige par annulation.

-- ============================================================
-- Moyens de paiement
-- ============================================================

CREATE TABLE payment_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    libelle TEXT NOT NULL,
    is_cash INTEGER NOT NULL DEFAULT 0 CHECK (is_cash IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

INSERT INTO
    payment_methods (code, libelle, is_cash)
VALUES ('ESPECES', 'Espèces', 1),
    (
        'MOBILE_MONEY',
        'Mobile Money',
        0
    ),
    ('CARTE', 'Carte bancaire', 0),
    (
        'VIREMENT',
        'Virement bancaire',
        0
    ),
    ('AUTRE', 'Autre', 0);

-- ============================================================
-- Numérotation automatique
-- ============================================================

CREATE TABLE document_sequences (
    type TEXT PRIMARY KEY,
    prefixe TEXT NOT NULL,
    largeur INTEGER NOT NULL DEFAULT 6 CHECK (largeur BETWEEN 3 AND 10),
    annee INTEGER NOT NULL DEFAULT 0,
    prochain_numero INTEGER NOT NULL DEFAULT 1 CHECK (prochain_numero >= 1)
);

INSERT INTO
    document_sequences (type, prefixe)
VALUES ('VENTE', 'V'),
    ('FACTURE', 'F'),
    ('PAIEMENT', 'P');

-- ============================================================
-- Sessions de caisse
-- ============================================================

CREATE TABLE cash_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id),
    ouverte_le TEXT NOT NULL,
    fond_ouverture INTEGER NOT NULL DEFAULT 0 CHECK (fond_ouverture >= 0),
    fermee_le TEXT,
    montant_attendu INTEGER,
    montant_compte INTEGER CHECK (
        montant_compte IS NULL
        OR montant_compte >= 0
    ),
    ecart INTEGER,
    statut TEXT NOT NULL DEFAULT 'OUVERTE' CHECK (
        statut IN ('OUVERTE', 'CLOTUREE')
    ),
    CHECK (
        (
            statut = 'OUVERTE'
            AND fermee_le IS NULL
        )
        OR (
            statut = 'CLOTUREE'
            AND fermee_le IS NOT NULL
            AND montant_compte IS NOT NULL
        )
    )
);

CREATE UNIQUE INDEX idx_cash_one_open_per_user ON cash_sessions (user_id)
WHERE
    statut = 'OUVERTE';

-- ============================================================
-- Ventes
-- ============================================================

CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_vente TEXT NOT NULL UNIQUE,
    token_idempotence TEXT NOT NULL UNIQUE,
    date_vente TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users (id),
    cash_session_id INTEGER NOT NULL REFERENCES cash_sessions (id),
    client_nom TEXT,
    client_telephone TEXT,
    montant_brut INTEGER NOT NULL CHECK (montant_brut >= 0),
    remise_globale INTEGER NOT NULL DEFAULT 0 CHECK (remise_globale >= 0),
    taux_taxe_bp INTEGER NOT NULL DEFAULT 0 CHECK (taux_taxe_bp >= 0),
    taxes INTEGER NOT NULL DEFAULT 0 CHECK (taxes >= 0),
    montant_net INTEGER NOT NULL CHECK (montant_net >= 0),
    statut TEXT NOT NULL DEFAULT 'VALIDEE' CHECK (
        statut IN ('VALIDEE', 'ANNULEE')
    ),
    annulee_le TEXT,
    annulee_par INTEGER REFERENCES users (id),
    motif_annulation TEXT,
    CHECK (
        remise_globale <= montant_brut
    ),
    CHECK (
        statut = 'VALIDEE'
        OR (
            annulee_le IS NOT NULL
            AND annulee_par IS NOT NULL
            AND motif_annulation IS NOT NULL
        )
    )
);

CREATE INDEX idx_sales_date ON sales (date_vente);

CREATE INDEX idx_sales_user_date ON sales (user_id, date_vente);

-- ============================================================
-- Lignes de vente
-- Une ligne correspond à un produit prélevé sur un lot précis.
-- ============================================================

CREATE TABLE sale_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales (id),
    product_id INTEGER NOT NULL REFERENCES products (id),
    lot_id INTEGER NOT NULL REFERENCES lots (id),
    conditionnement TEXT NOT NULL CHECK (
        conditionnement IN ('UNITE', 'SOUS_UNITE')
    ),
    quantite INTEGER NOT NULL CHECK (quantite > 0),
    quantite_base INTEGER NOT NULL CHECK (quantite_base > 0),
    prix_unitaire INTEGER NOT NULL CHECK (prix_unitaire >= 0),
    cout_total INTEGER NOT NULL DEFAULT 0 CHECK (cout_total >= 0),
    remise INTEGER NOT NULL DEFAULT 0 CHECK (remise >= 0),
    montant_ligne INTEGER NOT NULL CHECK (montant_ligne >= 0),
    CHECK (
        remise <= quantite * prix_unitaire
    ),
    CHECK (
        montant_ligne = quantite * prix_unitaire - remise
    )
);

CREATE INDEX idx_sale_lines_sale ON sale_lines (sale_id);

CREATE INDEX idx_sale_lines_lot ON sale_lines (lot_id);

CREATE INDEX idx_sale_lines_product ON sale_lines (product_id);

-- ============================================================
-- Paiements et remboursements
-- ============================================================

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL UNIQUE,
    sale_id INTEGER NOT NULL REFERENCES sales (id),
    payment_method_id INTEGER NOT NULL REFERENCES payment_methods (id),
    cash_session_id INTEGER NOT NULL REFERENCES cash_sessions (id),
    type TEXT NOT NULL CHECK (
        type IN (
            'ENCAISSEMENT',
            'REMBOURSEMENT'
        )
    ),
    montant INTEGER NOT NULL CHECK (montant > 0),
    date_paiement TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users (id),
    note TEXT
);

CREATE INDEX idx_payments_sale ON payments (sale_id);

CREATE INDEX idx_payments_session ON payments (cash_session_id);

-- ============================================================
-- Factures
-- ============================================================

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_facture TEXT NOT NULL UNIQUE,
    sale_id INTEGER NOT NULL UNIQUE REFERENCES sales (id),
    emise_le TEXT NOT NULL,
    emise_par INTEGER NOT NULL REFERENCES users (id),
    client_nom TEXT,
    client_telephone TEXT,
    chemin_pdf TEXT
);

-- ============================================================
-- Vue : solde des ventes
-- ============================================================

CREATE VIEW v_sales_balance AS
SELECT
    s.id AS sale_id,
    COALESCE(
        SUM(
            CASE p.type
                WHEN 'ENCAISSEMENT' THEN p.montant
                WHEN 'REMBOURSEMENT' THEN - p.montant
            END
        ),
        0
    ) AS montant_paye,
    CASE
        WHEN s.statut = 'ANNULEE' THEN 0
        ELSE s.montant_net - COALESCE(
            SUM(
                CASE p.type
                    WHEN 'ENCAISSEMENT' THEN p.montant
                    WHEN 'REMBOURSEMENT' THEN - p.montant
                END
            ),
            0
        )
    END AS reste
FROM sales s
    LEFT JOIN payments p ON p.sale_id = s.id
GROUP BY
    s.id;

-- ============================================================
-- Protection des opérations financières
-- ============================================================

CREATE TRIGGER sales_no_delete
BEFORE DELETE ON sales
BEGIN
    SELECT RAISE(ABORT, 'Une vente ne peut pas être supprimée, annulez-la');
END;

CREATE TRIGGER sales_protect
BEFORE UPDATE ON sales
WHEN OLD.statut = 'ANNULEE'
  OR NEW.numero_vente != OLD.numero_vente
  OR NEW.token_idempotence != OLD.token_idempotence
  OR NEW.date_vente != OLD.date_vente
  OR NEW.user_id != OLD.user_id
  OR NEW.cash_session_id != OLD.cash_session_id
  OR NEW.montant_brut != OLD.montant_brut
  OR NEW.remise_globale != OLD.remise_globale
  OR NEW.taux_taxe_bp != OLD.taux_taxe_bp
  OR NEW.taxes != OLD.taxes
  OR NEW.montant_net != OLD.montant_net
BEGIN
    SELECT RAISE(ABORT, 'Une vente validée ne peut plus être modifiée');
END;

CREATE TRIGGER sales_session_open
BEFORE INSERT ON sales
WHEN (
    SELECT statut
    FROM cash_sessions
    WHERE id = NEW.cash_session_id
) != 'OUVERTE'
BEGIN
    SELECT RAISE(ABORT, 'La session de caisse est clôturée');
END;

CREATE TRIGGER sale_lines_no_update
BEFORE UPDATE ON sale_lines
BEGIN
    SELECT RAISE(ABORT, 'sale_lines est immuable');
END;

CREATE TRIGGER sale_lines_no_delete
BEFORE DELETE ON sale_lines
BEGIN
    SELECT RAISE(ABORT, 'sale_lines est immuable');
END;

CREATE TRIGGER payments_no_update
BEFORE UPDATE ON payments
BEGIN
    SELECT RAISE(ABORT, 'payments est immuable');
END;

CREATE TRIGGER payments_no_delete
BEFORE DELETE ON payments
BEGIN
    SELECT RAISE(ABORT, 'payments est immuable');
END;

CREATE TRIGGER payments_session_open
BEFORE INSERT ON payments
WHEN (
    SELECT statut
    FROM cash_sessions
    WHERE id = NEW.cash_session_id
) != 'OUVERTE'
BEGIN
    SELECT RAISE(ABORT, 'La session de caisse est clôturée');
END;

-- Un encaissement ne peut pas dépasser le montant restant.
CREATE TRIGGER payments_no_overpay
BEFORE INSERT ON payments
WHEN NEW.type = 'ENCAISSEMENT'
 AND COALESCE(
     (
         SELECT SUM(
             CASE type
                 WHEN 'ENCAISSEMENT' THEN montant
                 ELSE -montant
             END

)
         FROM payments
         WHERE sale_id = NEW.sale_id
     ),
     0
 ) + NEW.montant > (
     SELECT montant_net
     FROM sales
     WHERE id = NEW.sale_id
 )
BEGIN
    SELECT RAISE(ABORT, 'Le paiement dépasse le montant restant à payer');

END;

-- Un remboursement ne peut pas dépasser les sommes encaissées.
CREATE TRIGGER payments_no_over_refund
BEFORE INSERT ON payments
WHEN NEW.type = 'REMBOURSEMENT'
 AND COALESCE(
     (
         SELECT SUM(
             CASE type
                 WHEN 'ENCAISSEMENT' THEN montant
                 ELSE -montant
             END

)
         FROM payments
         WHERE sale_id = NEW.sale_id
     ),
     0
 ) - NEW.montant < 0
BEGIN
    SELECT RAISE(ABORT, 'Le remboursement dépasse les sommes encaissées');

END;

CREATE TRIGGER cash_sessions_closed_immutable
BEFORE UPDATE ON cash_sessions
WHEN OLD.statut = 'CLOTUREE'
BEGIN
    SELECT RAISE(ABORT, 'Une session clôturée ne peut plus être modifiée');
END;

CREATE TRIGGER cash_sessions_no_delete
BEFORE DELETE ON cash_sessions
BEGIN
    SELECT RAISE(ABORT, 'Une session de caisse ne peut pas être supprimée');
END;

CREATE TRIGGER invoices_no_delete
BEFORE DELETE ON invoices
BEGIN
    SELECT RAISE(ABORT, 'Une facture ne peut pas être supprimée');
END;

CREATE TRIGGER invoices_protect
BEFORE UPDATE ON invoices
WHEN NEW.numero_facture != OLD.numero_facture
  OR NEW.sale_id != OLD.sale_id
  OR NEW.emise_le != OLD.emise_le
  OR NEW.emise_par != OLD.emise_par
BEGIN
    SELECT RAISE(ABORT, 'Une facture émise ne peut plus être modifiée');
END;

-- ============================================================
-- Paramètres de la pharmacie
-- ============================================================

INSERT INTO
    app_settings (cle, valeur)
VALUES ('pharmacie_nom', 'Pharmacie'),
    ('pharmacie_adresse', ''),
    ('pharmacie_telephone', ''),
    ('pharmacie_mention', ''),
    ('taxe_libelle', 'TVA'),
    ('taxe_vente_bp', '0'),
    ('remise_max_pct_ADMIN', '100'),
    (
        'remise_max_pct_PHARMACIEN',
        '30'
    ),
    (
        'remise_max_pct_CAISSIER',
        '10'
    );