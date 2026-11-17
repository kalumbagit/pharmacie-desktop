"""Horodatage : UTC, format ISO 8601 à la seconde."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit

from app.core.errors import ValidationError

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime(ISO_FORMAT)


def from_iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=UTC)

def iso_date(value: str | date | datetime | QDate | QDateEdit | None) -> str:
    """Convertit une date en chaîne ISO (AAAA-MM-JJ)."""
    if not value:
        return ""

    if isinstance(value, QDateEdit):
        return value.date().toString("yyyy-MM-dd")

    if isinstance(value, QDate):
        return value.toString("yyyy-MM-dd")

    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")

    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return str(value)


def format_local(value: str | None) -> str:
    """Affiche un horodatage ISO UTC en heure locale (jj/mm/aaaa hh:mm)."""
    if not value:
        return "Jamais"
    return from_iso(value).astimezone().strftime("%d/%m/%Y %H:%M")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def local_today(clock: Callable[[], datetime] = now_utc) -> date:
    """Date du jour en heure locale (celle que voit le pharmacien)."""
    return clock().astimezone().date()


def parse_date(value: str, label: str) -> str:
    """Valide une date AAAA-MM-JJ et la retourne normalisée."""
    text = value.strip()
    try:
        if not _DATE_RE.match(text):
            raise ValueError
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValidationError(f"{label} : date invalide (format AAAA-MM-JJ).") from None


def format_date(value: str | None) -> str:
    """AAAA-MM-JJ -> JJ/MM/AAAA."""
    if not value:
        return ""
    year, month, day = value.split("-")
    return f"{day}/{month}/{year}"


def format_fcfa(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " FCFA"

def local_day_bounds(day: date) -> tuple[str, str]:
    """Début (inclus) et fin (exclue) d'une journée LOCALE, en horodatages ISO UTC."""
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return to_iso(start), to_iso(end)