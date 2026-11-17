-- Paramètres applicatifs (clé/valeur) : informations de la pharmacie, taxes, numérotation...
CREATE TABLE app_settings (
    cle TEXT PRIMARY KEY,
    valeur TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT(
        strftime ('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

INSERT INTO app_settings (cle, valeur) VALUES ('devise', 'FCFA');