from io import StringIO
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from .models import Tenant


class TenantTests(TestCase):
    def test_normalization_and_database_subdomain_validation(self):
        tenant = Tenant.objects.create(nome='Marcos', subdomain=' MARCOS ')
        self.assertEqual(tenant.subdomain, 'marcos')
        for subdomain in ['marcos', 'MARCOS', 'a.b', '-bad', 'a' * 64]:
            with self.subTest(subdomain=subdomain), self.assertRaises(IntegrityError), transaction.atomic():
                Tenant.objects.bulk_create([Tenant(nome='Outro', subdomain=subdomain)])

    def test_timezone_validation_and_request_restoration(self):
        with self.assertRaises(ValidationError):
            Tenant.objects.create(nome='Inválido', subdomain='invalido', timezone='No/Such_Zone')
        Tenant.objects.create(nome='Sofia', subdomain='sofia', timezone='Europe/Lisbon')
        previous = timezone.get_current_timezone_name()
        self.client.get('/', HTTP_HOST='sofia.localhost')
        self.assertEqual(timezone.get_current_timezone_name(), previous)

    def test_development_seed_is_idempotent_and_preserves_existing_values(self):
        with self.settings(DEBUG=True):
            call_command('criar_tenants_dev', stdout=StringIO())
            Tenant.objects.filter(subdomain='marcos').update(ativo=False, nome='Personalizado')
            call_command('criar_tenants_dev', stdout=StringIO())
        self.assertEqual(Tenant.objects.count(), 3)
        tenant = Tenant.objects.get(subdomain='marcos')
        self.assertFalse(tenant.ativo)
        self.assertEqual(tenant.nome, 'Personalizado')
