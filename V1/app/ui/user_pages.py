"""Pages de gestion des utilisateurs : liste, formulaire, mot de passe temporaire."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.core.security import POLICY_HINT
from app.core.utils import format_local, from_iso, now_utc
from app.models import Role, User
from app.ui.theme import CardPage, fit_columns, make_button, make_label, make_table

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_COLUMNS = ["Identifiant", "Nom complet", "Rôle", "Statut", "Dernière connexion"]
_GREY = QBrush(QColor(120, 120, 120))


class UsersPage(QWidget):
    """Liste des utilisateurs : créer, modifier, activer/désactiver, réinitialiser."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__()
        self.win = win
        self._users: list[User] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(make_label("Gestion des utilisateurs", "title"))

        self.btn_new = make_button("Nouvel utilisateur")
        self.btn_edit = make_button("Modifier", "secondary")
        self.btn_toggle = make_button("Désactiver", "secondary")
        self.btn_reset = make_button("Réinitialiser le mot de passe", "secondary")
        self.btn_refresh = make_button("Actualiser", "secondary")
        self.btn_new.clicked.connect(lambda _checked=False: win.show_user_form(None))
        self.btn_edit.clicked.connect(lambda _checked=False: self._edit())
        self.btn_toggle.clicked.connect(lambda _checked=False: self._toggle_active())
        self.btn_reset.clicked.connect(lambda _checked=False: self._reset_password())
        self.btn_refresh.clicked.connect(lambda _checked=False: self.reload())

        bar = QHBoxLayout()
        bar.setSpacing(8)
        for button in (self.btn_new, self.btn_edit, self.btn_toggle, self.btn_reset):
            bar.addWidget(button)
        bar.addStretch(1)
        bar.addWidget(self.btn_refresh)
        layout.addLayout(bar)

        self.table = make_table(_COLUMNS, stretch_column=1)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._edit())
        layout.addWidget(self.table, 1)

        self.reload()

    # --- affichage ---------------------------------------------------------------
    def reload(self) -> None:
        selected = self._selected()
        selected_id = selected.id if selected else None
        try:
            self._users = self.win.users.list_users(self.win.ctx)
            roles = self.win.users.list_roles(self.win.ctx)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return

        labels = {r.code: r.libelle for r in roles}
        now = now_utc()
        self.table.setRowCount(len(self._users))
        for row, user in enumerate(self._users):
            locked = bool(user.locked_until and from_iso(user.locked_until) > now)
            if not user.is_active:
                status = "Désactivé"
            elif locked:
                status = "Verrouillé"
            else:
                status = "Actif"
            cells = [
                user.identifiant,
                user.nom_complet,
                labels.get(user.role_code, user.role_code),
                status,
                format_local(user.last_login_at),
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if not user.is_active:
                    item.setForeground(_GREY)
                self.table.setItem(row, column, item)
            if user.id == selected_id:
                self.table.selectRow(row)
        fit_columns(self.table)
        self._update_buttons()

    def _selected(self) -> User | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._users) and self.table.selectedItems():
            return self._users[row]
        return None

    def _update_buttons(self) -> None:
        user = self._selected()
        for button in (self.btn_edit, self.btn_toggle, self.btn_reset):
            button.setEnabled(user is not None)
        inactive = user is not None and not user.is_active
        self.btn_toggle.setText("Réactiver" if inactive else "Désactiver")

    # --- actions -----------------------------------------------------------------
    def _edit(self) -> None:
        user = self._selected()
        if user is not None:
            self.win.show_user_form(user)

    def _toggle_active(self) -> None:
        user = self._selected()
        if user is None:
            return
        activate = not user.is_active
        if not activate:
            answer = QMessageBox.question(
                self,
                "Désactiver le compte",
                f"Désactiver le compte « {user.identifiant} » ?\n"
                "L'utilisateur ne pourra plus se connecter.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.win.users.set_active(self.win.ctx, user.id, activate)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        self.reload()

    def _reset_password(self) -> None:
        user = self._selected()
        if user is None:
            return
        answer = QMessageBox.question(
            self,
            "Réinitialiser le mot de passe",
            f"Générer un nouveau mot de passe temporaire pour « {user.identifiant} » ?\n"
            "L'ancien mot de passe ne fonctionnera plus.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            temporary = self.win.users.reset_password(self.win.ctx, user.id)
        except AppError as exc:
            QMessageBox.warning(self, "Action impossible", str(exc))
            return
        self.win.show_temp_password(user.identifiant, temporary)


class UserFormPage(CardPage):
    """Création (user=None) ou modification d'un utilisateur."""

    def __init__(self, win: MainWindow, user: User | None = None) -> None:
        super().__init__("Modifier l'utilisateur" if user else "Nouvel utilisateur")
        self.win = win
        self._user = user

        self.identifiant = QLineEdit(user.identifiant if user else "")
        self.identifiant.setEnabled(user is None)  # l'identifiant ne change pas
        self.nom = QLineEdit(user.nom if user else "")
        self.prenom = QLineEdit(user.prenom if user else "")
        self.role = QComboBox()
        self.form.addRow("Identifiant", self.identifiant)
        self.form.addRow("Nom", self.nom)
        self.form.addRow("Prénom", self.prenom)
        self.form.addRow("Rôle", self.role)

        roles: list[Role] = []
        try:
            roles = win.users.list_roles(win.ctx)
        except AppError as exc:
            self.set_error(str(exc))
        for role in roles:
            self.role.addItem(role.libelle, role.code)
        if user is not None:
            index = self.role.findData(user.role_code)
            if index >= 0:
                self.role.setCurrentIndex(index)

        self.manual = QCheckBox("Définir le mot de passe temporaire manuellement")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setEnabled(False)
        self.manual.toggled.connect(self.password.setEnabled)
        if user is None:
            index = self.body.indexOf(self.error)
            self.body.insertWidget(index, self.manual)
            self.body.insertWidget(index + 1, self.password)
            self.body.insertWidget(
                index + 2,
                make_label(
                    f"Sinon, un mot de passe est généré automatiquement. ({POLICY_HINT})",
                    "muted",
                ),
            )

        save = make_button("Enregistrer")
        save.clicked.connect(lambda _checked=False: self._submit())
        cancel = make_button("Annuler", "secondary")
        cancel.clicked.connect(lambda _checked=False: win.show_users())
        self.add_buttons(cancel, save)

    def _submit(self) -> None:
        role_code = self.role.currentData()
        try:
            if self._user is None:
                created = self.win.users.create_user(
                    self.win.ctx,
                    identifiant=self.identifiant.text(),
                    nom=self.nom.text(),
                    prenom=self.prenom.text(),
                    role_code=role_code,
                    password=self.password.text() if self.manual.isChecked() else None,
                )
            else:
                self.win.users.update_user(
                    self.win.ctx,
                    self._user.id,
                    nom=self.nom.text(),
                    prenom=self.prenom.text(),
                    role_code=role_code,
                )
        except AppError as exc:
            self.set_error(str(exc))
            return
        if self._user is None:
            self.win.show_temp_password(created.user.identifiant, created.temporary_password)
        else:
            self.win.show_users()


class TempPasswordPage(CardPage):
    """Affiche une seule fois le mot de passe temporaire à communiquer à l'utilisateur."""

    def __init__(self, win: MainWindow, identifiant: str, password: str) -> None:
        super().__init__(
            "Mot de passe temporaire",
            f"Communiquez ces identifiants à l'utilisateur « {identifiant} ». "
            "À sa première connexion, il devra définir son propre mot de passe.",
        )
        self.password_field = QLineEdit(password)
        self.password_field.setReadOnly(True)
        self.form.addRow("Mot de passe", self.password_field)
        self.set_error("Ce mot de passe ne sera plus affiché après avoir quitté cette page.")

        copy = make_button("Copier", "secondary")
        copy.clicked.connect(
            lambda _checked=False: QGuiApplication.clipboard().setText(self.password_field.text())
        )
        done = make_button("Terminé")
        done.clicked.connect(lambda _checked=False: win.show_users())
        self.add_buttons(copy, done)