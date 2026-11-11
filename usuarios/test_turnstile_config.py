from unittest.mock import patch

from django.contrib.admin.models import LogEntry, CHANGE
from django.db import IntegrityError, transaction
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse

from . import turnstile
from .models import ConfiguracaoTurnstile, User
from tenants.models import Tenant


@override_settings(
    DEBUG=False, TURNSTILE_ENABLED=True, TENANT_BASE_DOMAIN='localhost',
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='',
    TURNSTILE_PUBLIC_SITE_KEY='public-real', TURNSTILE_PUBLIC_SECRET_KEY='public-secret',
    TURNSTILE_AUTH_SITE_KEY='auth-real', TURNSTILE_AUTH_SECRET_KEY='auth-secret',
)
class TurnstileConfigurationTests(TestCase):
    def setUp(self):
        self.config, _ = ConfiguracaoTurnstile.objects.get_or_create(pk=1)
        self.factory = RequestFactory()
        self.client.defaults['HTTP_HOST'] = 'localhost'

    def test_default_and_missing_configuration_keep_protection(self):
        self.assertTrue(self.config.turnstile_ativo)
        self.assertTrue(turnstile.enabled())
        ConfiguracaoTurnstile.objects.all().delete()
        self.assertTrue(turnstile.enabled())

    def test_database_enforces_singleton(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConfiguracaoTurnstile.objects.bulk_create([ConfiguracaoTurnstile(pk=2)])

    def test_switch_controls_all_widgets_and_verifications_in_production(self):
        for active in (False, True):
            self.config.turnstile_ativo = active
            self.config.save()
            for widget, action in (
                (turnstile.AUTH, turnstile.ACTION_LOGIN),
                (turnstile.AUTH, turnstile.ACTION_REGISTRATION),
                (turnstile.PUBLIC, turnstile.ACTION_BOOKING),
            ):
                with self.subTest(active=active, action=action), patch(
                    'usuarios.turnstile._post_siteverify',
                ) as siteverify:
                    self.assertEqual(turnstile.enabled(), active)
                    self.assertEqual(turnstile.widget_context(widget, action) is not None, active)
                    result = turnstile.verify(self.factory.post('/'), widget, action)
                    self.assertEqual(result.ok, not active)
                    siteverify.assert_not_called()

    def test_global_admin_can_change_and_change_is_audited(self):
        admin = User.objects.create_superuser('global@example.com', 'admin-password')
        self.client.force_login(admin)
        url = reverse('admin:usuarios_configuracaoturnstile_change', args=[1])
        response = self.client.post(url, {}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.config.refresh_from_db()
        self.assertFalse(self.config.turnstile_ativo)
        self.assertEqual(self.config.atualizado_por, admin)
        self.assertContains(response, 'sem CAPTCHA')
        self.assertTrue(LogEntry.objects.filter(
            user=admin, object_id='1', action_flag=CHANGE,
            content_type__model='configuracaoturnstile',
        ).exists())
        response = self.client.post(url, {'turnstile_ativo': 'on'})
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertTrue(self.config.turnstile_ativo)
        self.assertEqual(self.client.get(reverse('admin:usuarios_configuracaoturnstile_add')).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin:usuarios_configuracaoturnstile_delete', args=[1])).status_code, 403)

    def test_tenant_admin_cannot_change_platform_configuration(self):
        tenant = Tenant.objects.create(nome='Teste', subdomain='teste')
        user = User.objects.create_user('tenant@example.com', 'admin-password', tenant=tenant, tipo='ADMIN', is_staff=True)
        self.client.force_login(user)
        self.client.post(reverse('admin:usuarios_configuracaoturnstile_change', args=[1]), {})
        self.config.refresh_from_db()
        self.assertTrue(self.config.turnstile_ativo)
        self.assertIsNone(self.config.atualizado_por)
