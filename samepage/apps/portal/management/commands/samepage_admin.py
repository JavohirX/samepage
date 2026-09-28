"""Bootstrap a production instance: create (or promote) a global admin.

    docker compose exec app python manage.py samepage_admin --email you@example.org --name "You"

The password is read from SAMEPAGE_ADMIN_PASSWORD, or typed at a prompt (not echoed). It is
never a command-line argument, so it does not land in shell history or `ps`. The admin then
signs in at /login and creates the first event at /e/new.
"""

from __future__ import annotations

import getpass
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from samepage.apps.portal.models import Person
from samepage.core.errors import Unprocessable
from samepage.services import accounts


class Command(BaseCommand):
    help = "Create a global admin (or make an existing account one) with a password you choose."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            email = accounts.clean_email(options["email"])
        except Unprocessable as exc:
            raise CommandError(str(exc.detail)) from exc
        password = os.environ.get("SAMEPAGE_ADMIN_PASSWORD")
        if not password:
            if not os.isatty(0):
                raise CommandError("Set SAMEPAGE_ADMIN_PASSWORD, or run with a terminal to type the password.")
            password = getpass.getpass("Password for the admin: ")
            if password != getpass.getpass("Again: "):
                raise CommandError("The two passwords differ.")
        try:
            accounts.check_new_password(password)
        except Unprocessable as exc:
            raise CommandError(str(exc.detail)) from exc
        person = Person.objects.filter(email=email).first()
        if person is None:
            person = Person.objects.create_superuser(email, password=password, name=options["name"] or email)
            self.stdout.write(f"created admin {person.id} {person.email}")
        else:
            person.is_admin = True
            person.is_active = True
            person.set_password(password)
            if options["name"]:
                person.name = options["name"]
            person.save()
            self.stdout.write(f"promoted {person.id} {person.email} to admin and set the password")
