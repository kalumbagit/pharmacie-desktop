# Pharmacie : gestion de pharmacie (Python / PySide6 / SQLite)

```bash
uv sync
uv run python -m app.main     # lancer l'application
uv run pytest                 # tests
uv run ruff format . && uv run ruff check . --fix
```

## Structure

```
app/
  main.py            point d'entrée
  core/              config, database (connexion, transactions, migrations),
                     errors, security (mots de passe, permissions, contexte), utils
  models.py          dataclasses
  repositories.py    tout le SQL
  services/          logique métier + contrôle des permissions (auth.py, users.py, ...)
  ui/                interface : une seule fenêtre, pages chargées dans la zone de contenu
    theme.py         charte graphique (bleu clair / rouge rosé) et composants
    main_window.py   fenêtre unique, menu latéral, navigation
    *_pages.py       pages par module
  migrations/        0001_*.sql, 0002_*.sql ...
tests/
```

Règle : `ui` appelle `services`, `services` appelle `repositories`, qui exécutent le SQL.
Un nouveau module = un fichier `services/xxx.py` + un fichier `ui/xxx_pages.py`
+ une entrée dans le menu de `main_window.py`.
