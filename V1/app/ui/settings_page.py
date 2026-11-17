"""Paramètres de l'application (administrateur) : identité, taxe, remises, alertes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QDir
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from app.core.errors import AppError
from app.services.app_settings import DOCUMENTS_DIR_KEY, FIELDS
from app.ui.theme import CardPage, make_button, make_label, make_spin

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

TAX_KEY = "taxe_vente_bp"


class SettingsPage(CardPage):
    def __init__(self, win: MainWindow) -> None:
        super().__init__(
            "Paramètres",
            "Ces informations apparaissent sur les factures et pilotent la caisse.",
            width=640,
        )
        self.win = win
        self.fields: dict[str, QWidget] = {}

        try:
            values = win.app_settings.get_all(win.ctx)
        except AppError as exc:
            self.set_error(str(exc))
            values = {}

        # Pour savoir, à l'enregistrement, si le dossier des documents a changé.
        self._initial_documents_dir = values.get(DOCUMENTS_DIR_KEY, "")

        for field in FIELDS:
            raw = values.get(field.key, "")
            widget: QWidget

            if field.key == TAX_KEY:
                tax = QDoubleSpinBox()
                tax.setRange(0, 100)
                tax.setDecimals(2)
                tax.setSuffix(" %")
                tax.setValue(int(raw or 0) / 100)
                widget = tax
                label = "Taux de taxe sur les ventes"

            elif field.kind == "int":
                spin = make_spin(
                    maximum=field.maximum,
                    minimum=field.minimum,
                )
                spin.setValue(int(raw or field.minimum))
                widget = spin
                label = field.label

            else:
                widget = QLineEdit(raw)
                label = field.label

            self.fields[field.key] = widget

            if field.key == DOCUMENTS_DIR_KEY and isinstance(widget, QLineEdit):
                # Le champ reste un QLineEdit (lu par _values) ; on lui ajoute un bouton
                # « Parcourir… » qui ouvre l'explorateur de fichiers.
                self.form.addRow(label, self._with_browse_button(widget))
            else:
                self.form.addRow(label, widget)

        documents_field = self.fields.get(DOCUMENTS_DIR_KEY)
        if isinstance(documents_field, QLineEdit):
            documents_field.setPlaceholderText(str(win.settings.documents_dir))

        self.body.insertWidget(
            self.body.indexOf(self.error),
            make_label(
                "Taxe à 0 % : aucune taxe n'est ajoutée aux ventes.",
                "muted",
            ),
        )
        self.body.insertWidget(
            self.body.indexOf(self.error),
            make_label(
                f"Dossier des documents actuellement utilisé : {win.settings.documents_dir}\n"
                "(factures, reçus, fiches d'inventaire et logo.png pour le filigrane).",
                "muted",
            ),
        )

        save = make_button("Enregistrer")
        save.clicked.connect(lambda _checked=False: self._save())
        self.add_buttons(save)

    def _with_browse_button(self, edit: QLineEdit) -> QWidget:
        """Champ de saisie + bouton qui ouvre l'explorateur pour choisir un dossier."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        browse = make_button("Parcourir…", "secondary")
        browse.clicked.connect(lambda _checked=False: self._browse_documents_dir(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return container

    def _browse_documents_dir(self, edit: QLineEdit) -> None:
        """Ouvre l'explorateur, positionné sur le dossier actuel (ou le dossier par défaut)."""
        typed = edit.text().strip()
        start = Path(typed) if typed else Path(self.win.settings.documents_dir)
        if not start.is_dir():
            start = Path.home()

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choisir le dossier des documents",
            str(start),
        )
        if folder:  # chaîne vide = l'utilisateur a annulé
            edit.setText(QDir.toNativeSeparators(folder))

    def _values(self) -> dict[str, str]:
        result: dict[str, str] = {}

        for key, widget in self.fields.items():
            if isinstance(widget, QDoubleSpinBox):
                result[key] = str(round(widget.value() * 100))
            elif isinstance(widget, QSpinBox):
                result[key] = str(widget.value())
            elif isinstance(widget, QLineEdit):
                result[key] = widget.text()

        return result

    def _save(self) -> None:
        values = self._values()

        try:
            self.win.app_settings.update(self.win.ctx, values)
        except AppError as exc:
            self.set_error(str(exc))
            return

        self.set_error("")
        message = "Paramètres enregistrés."
        new_dir = " ".join(values.get(DOCUMENTS_DIR_KEY, "").split())

        if new_dir != self._initial_documents_dir:
            self._initial_documents_dir = new_dir
            message += (
                "\n\nLe nouveau dossier des documents sera utilisé au prochain "
                "démarrage de l'application. Copiez-y le fichier logo.png pour "
                "conserver le filigrane."
            )

        QMessageBox.information(
            self,
            "Paramètres",
            message,
        )