from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from tenants.models import Tenant
from usuarios.models import User


@override_settings(MERCADO_PAGO_ACCESS_TOKEN='', MERCADO_PAGO_WEBHOOK_SECRET='', PLATFORM_MONTHLY_PRICE='')
class MensalidadeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        cls.other = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        cls.admin = User.objects.create_user('billing-admin@example.test', tenant=cls.tenant, tipo='ADMIN')
        cls.customer = User.objects.create_user('billing-client@example.test', tenant=cls.tenant)
        cls.platform_admin = User.objects.create_superuser('platform@example.test')

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse('painel:mensalidade')
        self.host = {'HTTP_HOST': 'marcos.localhost'}

    def test_unconfigured_checkout_without_promotional_offer(self):
        page = self.client.get(self.url, {'status':'approved'}, **self.host)
        self.assertNotContains(page, 'Oferta de lançamento')
        self.assertNotContains(page, '20 primeiros cadastros')
        self.assertContains(page, 'Em configuração')
        self.assertContains(page, 'Pagamento ainda indisponível')
        self.assertEqual(page.context['dias_restantes'], 30)
        self.assertFalse(page.context['checkout_configurado'])
        self.assertIn('no-store', page['Cache-Control'])
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, self.tenant.data_expiracao)

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN='test-token', MERCADO_PAGO_WEBHOOK_SECRET='test-secret', PLATFORM_MONTHLY_PRICE='30.00')
    def test_subscription_configuration_and_expiration_read_only(self):
        self.tenant.expira_em = date(2026, 12, 31)
        self.tenant.save()
        page = self.client.get(self.url, **self.host)
        self.assertTrue(page.context['checkout_configurado'])
        self.assertEqual(page.context['valor_mensal'], Decimal('30.00'))
        self.assertContains(page, '31/12/2026')
        self.assertContains(page, '30 dias')
        self.assertNotContains(page, 'name="expira_em"')
        self.assertEqual(self.client.post(self.url, {'expira_em': '2099-12-31'}, **self.host).status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 12, 31))

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN='test-token', MERCADO_PAGO_WEBHOOK_SECRET='test-secret', PLATFORM_MONTHLY_PRICE='30.00')
    def test_post_starts_subscription_and_redirects_to_hosted_checkout(self):
        checkout = 'https://www.mercadopago.com.br/subscriptions/checkout?preapproval_id=123'
        with patch('painel.mensalidade_views.create_subscription', return_value=checkout) as start:
            response = self.client.post(self.url, {'acao': 'assinar'}, **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], checkout)
        start.assert_called_once_with(
            tenant_id=self.tenant.pk,
            payer_email=self.admin.email,
            amount=Decimal('30.00'),
        )

    @override_settings(PLATFORM_MONTHLY_PRICE='NaN')
    def test_invalid_config_does_not_enable_checkout(self):
        page = self.client.get(self.url, **self.host)
        self.assertEqual(page.context['checkout_url'], '')
        self.assertIsNone(page.context['valor_mensal'])

    def test_permissions_and_tenant_scope(self):
        self.assertEqual(self.client.get(self.url, HTTP_HOST='wanessa.localhost').status_code, 403)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url, **self.host).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url, **self.host).status_code, 302)

    def test_platform_admin_edits_expiration(self):
        self.client.force_login(self.platform_admin)
        url = reverse('admin:tenants_tenant_change', args=[self.tenant.pk])
        page = self.client.get(url, HTTP_HOST='localhost')
        self.assertContains(page, 'name="expira_em"')
        response = self.client.post(url, {'nome':'Marcos', 'subdomain':'marcos', 'ativo':'on',
            'timezone':'America/Sao_Paulo', 'expira_em':'31/12/2026', '_save':'Salvar'}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 12, 31))

    def test_daily_countdown_and_expiration_boundaries(self):
        self.tenant.expira_em = date(2026, 10, 31)
        self.tenant.save()
        for today, remaining, label in [
            (date(2026, 10, 1), 30, 'dias para expirar'),
            (date(2026, 10, 2), 29, 'dias para expirar'),
            (date(2026, 10, 30), 1, 'dia para expirar'),
            (date(2026, 10, 31), 0, 'Expira hoje'),
            (date(2026, 11, 1), 0, 'Prazo expirado'),
        ]:
            with self.subTest(today=today), patch('django.utils.timezone.localdate', return_value=today):
                page = self.client.get(self.url, **self.host)
                self.assertEqual(page.context['dias_restantes'], remaining)
                self.assertContains(page, label)

    def test_registration_date_and_tenant_timezone(self):
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 1, 1, tzinfo=timezone.utc)):
            tenant = Tenant.objects.create(nome='Teste', subdomain='teste', timezone='America/Sao_Paulo')
            self.assertEqual(tenant.expira_em, date(2026, 10, 30))
            self.assertEqual(tenant.dias_para_expirar, 30)
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 2, 1, tzinfo=timezone.utc)):
            tenant.nome = 'Nome alterado'
            tenant.save()
            tenant.refresh_from_db()
            self.assertEqual(tenant.expira_em, date(2026, 10, 30))
            self.assertEqual(tenant.dias_para_expirar, 29)

    def test_backfill_uses_original_creation_date_and_preserves_manual_dates(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        Tenant.objects.filter(pk=self.tenant.pk).update(
            expira_em=None, criado_em=datetime(2026, 9, 1, 1, tzinfo=timezone.utc))
        Tenant.objects.filter(pk=self.other.pk).update(expira_em=date(2027, 1, 1))
        migration = import_module('tenants.migrations.0005_alter_tenant_expira_em')
        migration.preencher_expiracao(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        self.tenant.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 9, 30))
        self.assertEqual(self.other.expira_em, date(2027, 1, 1))
