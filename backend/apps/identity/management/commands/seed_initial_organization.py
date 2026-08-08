import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.identity.models import Membership, Organization, Role


class Command(BaseCommand):
    help = "Create the initial organization, roles, and administrator."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        password = os.environ.get("SEED_ADMIN_PASSWORD")
        if not password:
            raise CommandError("SEED_ADMIN_PASSWORD must be set.")
        if not settings.DEBUG and password == "development-only-admin-password":
            raise CommandError("The development seed password is not allowed when DEBUG=False.")

        organization, _ = Organization.objects.get_or_create(
            slug=os.environ.get("SEED_ORGANIZATION_SLUG", "sinofgear"),
            defaults={"name": os.environ.get("SEED_ORGANIZATION_NAME", "SinofGear")},
        )
        administrator = Role.objects.create_administrator()
        Role.objects.create_operator()
        Role.objects.create_reviewer()
        Role.objects.create_read_only()

        username = os.environ.get("SEED_ADMIN_USERNAME", "admin")
        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
        Membership.objects.get_or_create(
            user=user,
            organization=organization,
            defaults={"role": administrator, "status": Membership.Status.ACTIVE},
        )
        self.stdout.write(self.style.SUCCESS("Initial organization seed is present."))
