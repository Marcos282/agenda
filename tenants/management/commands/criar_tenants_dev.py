from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from tenants.models import Tenant

class Command(BaseCommand):
    help = 'Cria marcos, wanessa e sofia sem alterar tenants existentes (desenvolvimento).'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Este comando é exclusivo para desenvolvimento (DEBUG=True).')
        for subdomain in ('marcos', 'wanessa', 'sofia'):
            tenant, created = Tenant.objects.get_or_create(subdomain=subdomain, defaults={'nome': subdomain.title()})
            self.stdout.write(f'{tenant.subdomain}: {"criado" if created else "já existe"}')
