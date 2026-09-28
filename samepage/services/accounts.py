"""Accounts: sign-up, password links an organizer hands out, and changing a password.

Passwords are hashed by Django's PBKDF2 hasher. A person created by an organizer has an
unusable password until they open their one-time link and choose one.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import Invite, Person
from samepage.core.errors import Conflict, Unprocessable
from samepage.domain.tokens import DEMO_PASSWORD

MIN_PASSWORD = 10
MAX_PASSWORD = 200
PASSWORD_LINK_DAYS = 14
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_email(value) -> str:
    if not isinstance(value, str):
        raise Unprocessable({"email": "Expected an email address."})
    email = value.strip().lower()
    if not _EMAIL.match(email) or len(email) > 254:
        raise Unprocessable({"email": "Expected an email address."})
    return email


def clean_name(value, *, required: bool = True) -> str:
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise Unprocessable({"name": "Expected a name."})
    name = value.strip()
    if len(name) > 120:
        raise Unprocessable({"name": "At most 120 characters."})
    return name


def check_new_password(value) -> str:
    if not isinstance(value, str):
        raise Unprocessable({"password": "Expected text."})
    if len(value) < MIN_PASSWORD:
        raise Unprocessable({"password": f"At least {MIN_PASSWORD} characters."})
    if len(value) > MAX_PASSWORD:
        raise Unprocessable({"password": f"At most {MAX_PASSWORD} characters."})
    if value == DEMO_PASSWORD:
        # The demo password is published in this repository.
        raise Unprocessable({"password": "That password is published in this repository. Choose another."})
    return value


@transaction.atomic
def signup(body: dict) -> Person:
    email = clean_email(body.get("email"))
    name = clean_name(body.get("name"))
    password = check_new_password(body.get("password"))
    if Person.objects.filter(email=email).exists():
        # Same answer whether or not the account can sign in, so the form is not an oracle for passwords.
        raise Conflict("An account with this email already exists. Sign in instead.")
    try:
        with transaction.atomic():
            return Person.objects.create_user(email, password=password, name=name)
    except IntegrityError as exc:
        raise Conflict("An account with this email already exists. Sign in instead.") from exc


def ensure_person(email: str, name: str) -> tuple[Person, bool]:
    """The person with this email, created without a usable password if new."""
    person = Person.objects.filter(email=email).first()
    if person is not None:
        return person, False
    return Person.objects.create_user(email, name=name or email.split("@", 1)[0]), True


def issue_password_link(person: Person, *, actor: str, event_id: str | None) -> str:
    """A one-time link that lets `person` choose a password. Earlier unused links stop working."""
    now = timezone.now()
    Invite.objects.filter(kind="password", person=person, revoked_at__isnull=True).update(revoked_at=now)
    token = "pw_" + secrets.token_urlsafe(24)
    Invite.objects.create(
        id="inv_" + secrets.token_hex(5),
        kind="password",
        event_id=event_id,
        person=person,
        token_sha256=digest(token),
        expires_at=now + timedelta(days=PASSWORD_LINK_DAYS),
        max_uses=1,
        created_by=actor,
    )
    return f"{settings.PUBLIC_URL.rstrip('/')}/password/{token}"


def _live_password_invite(token: str, *, lock: bool = False) -> Invite:
    rows = Invite.objects.filter(kind="password", token_sha256=digest(token)).select_related("person")
    if lock:
        # Lock the invite row only: the joined team/person side is nullable, so it cannot be locked.
        rows = rows.select_for_update(of=("self",))
    invite = rows.first()
    if invite is None or invite.revoked_at is not None or invite.uses >= invite.max_uses:
        raise NotFound("This link is not valid. Ask the organizer for a new one.")
    if invite.expires_at <= timezone.now():
        raise NotFound("This link has expired. Ask the organizer for a new one.")
    return invite


def password_link_preview(token: str) -> dict:
    invite = _live_password_invite(token)
    return {"email": invite.person.email, "name": invite.person.name, "expires_at": invite.expires_at}


@transaction.atomic
def use_password_link(token: str, body: dict) -> Person:
    invite = _live_password_invite(token, lock=True)
    password = check_new_password(body.get("password"))
    person = invite.person
    person.set_password(password)
    person.save(update_fields=["password"])
    invite.uses += 1
    invite.save(update_fields=["uses"])
    if invite.event_id:
        from samepage.services import audit

        audit.append(invite.event_id, person.id, "account.password_set", person.id, None, {"invite": invite.id})
    return person


@transaction.atomic
def change_password(person: Person, body: dict) -> Person:
    current = body.get("current_password")
    if not isinstance(current, str) or not check_password(current, person.password):
        raise Unprocessable({"current_password": "That is not your current password."})
    password = check_new_password(body.get("password"))
    person.set_password(password)
    person.save(update_fields=["password"])
    return person
