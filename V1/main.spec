# -*- mode: python ; coding: utf-8 -*-
"""
Configuration PyInstaller pour l'application « Pharmacie » (PySide6 / SQLite).

Mode ONEFILE : tout (binaires, modules, données) est passé directement à ``EXE``,
sans bloc ``COLLECT``. Le livrable est UN SEUL fichier portable :
    dist/Pharmacie.exe   (Windows)   |   dist/Pharmacie   (Linux/macOS)

Build (à lancer depuis la racine du projet, là où se trouve ce fichier) :
    uv run pyinstaller main.spec --clean
ou, sans uv :
    pip install pyinstaller && pyinstaller main.spec --clean

Données à l'exécution : l'application crée ``data/`` (base SQLite, logs, sauvegardes)
et ``documents/`` (factures, reçus, logo.png) À CÔTÉ de l'exécutable (voir
``app/core/config.py``). Le dossier peut donc être copié sur une clé USB.
"""

import os
import platform

block_cipher = None

# ``SPECPATH`` est fourni par PyInstaller : le .spec peut être lancé de n'importe où.
BASE_DIR = os.path.abspath(SPECPATH)
APP_DIR = os.path.join(BASE_DIR, "app")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# --- Icône (optionnelle : ignorée si le fichier n'existe pas) ---
if platform.system() == "Windows":
    ICON_PATH = os.path.join(ASSETS_DIR, "icon.ico")
elif platform.system() == "Darwin":
    ICON_PATH = os.path.join(ASSETS_DIR, "icon.icns")
else:
    ICON_PATH = os.path.join(ASSETS_DIR, "icon.png")

# --- Données embarquées ---
# Les migrations SQL sont lues au démarrage (app/core/database.py :
# ``Path(__file__).parents[1] / "migrations"``) : elles doivent donc être
# embarquées sous « app/migrations ».
datas = [
    (os.path.join(APP_DIR, "migrations"), os.path.join("app", "migrations")),
]
if os.path.isdir(ASSETS_DIR):
    datas.append((ASSETS_DIR, "assets"))

# --- Imports cachés ---
# Pillow charge ses plugins d'image dynamiquement (utilisé pour le filigrane du logo).
# ReportLab charge certaines tables de polices à la demande.
hiddenimports = [
    "PIL.PngImagePlugin",
    "PIL.JpegImagePlugin",
    "PIL.GifImagePlugin",
    "PIL.BmpImagePlugin",
    "PIL.WebPImagePlugin",
    "PIL.IcoImagePlugin",
    "reportlab.pdfbase._fontdata",
    "reportlab.pdfbase._fontdata_enc_winansi",
    "reportlab.pdfbase._fontdata_enc_macroman",
    "reportlab.pdfbase._fontdata_enc_standard",
    "reportlab.pdfbase._fontdata_enc_symbol",
    "reportlab.pdfbase._fontdata_enc_zapfdingbats",
    "reportlab.pdfbase._fontdata_widths_helvetica",
    "reportlab.pdfbase._fontdata_widths_helveticabold",
    "reportlab.pdfbase._fontdata_widths_helveticaoblique",
    "reportlab.pdfbase._fontdata_widths_helveticaboldoblique",
]

# === ANALYSE DU PROJET ===
a = Analysis(
    [os.path.join(APP_DIR, "main.py")],  # Point d'entrée (imports « from app.… »)
    pathex=[BASE_DIR],                   # Racine du projet : rend le paquet ``app`` importable
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Modules lourds de PySide6 / bibliothèques inutilisés : exécutable plus léger.
    excludes=[
        "tests",
        "pytest",
        "pytestqt",
        "ruff",
        "tkinter",
        "unittest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtNetwork",
        "PySide6.QtBluetooth",
        "PySide6.QtSensors",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# === EXÉCUTABLE UNIQUE (ONEFILE) ===
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,           # DLL / .so embarquées dans l'exécutable
    a.zipfiles,
    a.datas,              # Migrations SQL (+ assets) embarquées
    [],
    exclude_binaries=False,   # ONEFILE : pas de COLLECT, un seul fichier
    name="Pharmacie",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX désactivé : il corrompt parfois les DLL Qt et déclenche des faux positifs antivirus
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # Application graphique : pas de fenêtre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)

# Pas de bloc COLLECT : dist/Pharmacie(.exe) est le livrable final.