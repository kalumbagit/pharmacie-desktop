"""Pages d'authentification : installation initiale, connexion, changement de mot de passe."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLineEdit

from app.core.errors import AppError
from app.core.security import POLICY_HINT
from app.ui.theme import CardPage, make_button, make_label, password_edit

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


class SetupPage(CardPage):
    """Affichée une seule fois : création du premier compte administrateur."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__(
            "Installation",
            "Aucun utilisateur n'existe encore. Créez le compte administrateur principal.",
        )
        self.win = win
        self.identifiant = QLineEdit()
        self.nom = QLineEdit()
        self.prenom = QLineEdit()
        self.password = password_edit()
        self.confirm = password_edit()
        self.form.addRow("Identifiant", self.identifiant)
        self.form.addRow("Nom", self.nom)
        self.form.addRow("Prénom", self.prenom)
        self.form.addRow("Mot de passe", self.password)
        self.form.addRow("Confirmation", self.confirm)
        self.body.insertWidget(self.body.indexOf(self.error), make_label(POLICY_HINT, "muted"))

        button = make_button("Créer le compte")
        button.clicked.connect(self._submit)
        self.confirm.returnPressed.connect(self._submit)
        self.add_buttons(button)
        self.identifiant.setFocus()

    def _submit(self) -> None:
        if self.password.text() != self.confirm.text():
            self.set_error("La confirmation ne correspond pas au mot de passe.")
            return
        try:
            self.win.auth.create_first_admin(
                self.identifiant.text(), self.nom.text(), self.prenom.text(), self.password.text()
            )
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.show_login()


class LoginPage(CardPage):
    def __init__(self, win: MainWindow) -> None:
        super().__init__("Connexion", "Identifiez-vous pour accéder à l'application.")
        self.win = win
        self.identifiant = QLineEdit()
        self.password = password_edit()
        self.form.addRow("Identifiant", self.identifiant)
        self.form.addRow("Mot de passe", self.password)

        button = make_button("Se connecter")
        button.clicked.connect(self._submit)
        self.identifiant.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._submit)
        self.add_buttons(button)
        self.identifiant.setFocus()

    def _submit(self) -> None:
        try:
            context = self.win.auth.login(self.identifiant.text(), self.password.text())
        except AppError as exc:
            self.set_error(str(exc))
            self.password.clear()
            self.password.setFocus()
            return
        self.win.login_succeeded(context)


class ChangePasswordPage(CardPage):
    """Si `forced`, l'utilisateur doit changer son mot de passe ou se déconnecter."""

    def __init__(self, win: MainWindow, forced: bool = False) -> None:
        super().__init__(
            "Définir votre mot de passe" if forced else "Changer mon mot de passe",
            "Pour des raisons de sécurité, vous devez choisir votre propre mot de passe "
            "avant de continuer."
            if forced
            else "Choisissez un nouveau mot de passe.",
        )
        self.win = win
        self.old = password_edit()
        self.new = password_edit()
        self.confirm = password_edit()
        self.form.addRow("Mot de passe actuel", self.old)
        self.form.addRow("Nouveau mot de passe", self.new)
        self.form.addRow("Confirmation", self.confirm)
        self.body.insertWidget(self.body.indexOf(self.error), make_label(POLICY_HINT, "muted"))

        validate = make_button("Valider")
        validate.clicked.connect(self._submit)
        self.confirm.returnPressed.connect(self._submit)
        if forced:
            cancel = make_button("Se déconnecter", "secondary")
            cancel.clicked.connect(lambda _checked=False: win.logout())
        else:
            cancel = make_button("Annuler", "secondary")
            cancel.clicked.connect(lambda _checked=False: win.show_home())
        self.add_buttons(cancel, validate)
        self.old.setFocus()

    def _submit(self) -> None:
        if self.new.text() != self.confirm.text():
            self.set_error("La confirmation ne correspond pas au nouveau mot de passe.")
            return
        try:
            context = self.win.auth.change_password(self.win.ctx, self.old.text(), self.new.text())
        except AppError as exc:
            self.set_error(str(exc))
            return
        self.win.password_changed(context)
