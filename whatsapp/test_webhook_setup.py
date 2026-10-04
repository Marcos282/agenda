from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from django.core.management import call_command, CommandError
from whatsapp.inbox_views import webhook_token


@override_settings(STORE_BASE_DOMAIN='tacombinado.net', EVOLUTION_INSTANCE_PREFIX='combinado_tenant')
class WebhookSetupTests(SimpleTestCase):
    def setUp(self):
        self.tenant = SimpleNamespace(pk=4, nome='Marcos', subdomain='marcos')

    @patch('whatsapp.management.commands.configurar_webhook_testes.verify_endpoint')
    @patch('whatsapp.management.commands.configurar_webhook_testes.evolution.request')
    @patch('whatsapp.management.commands.configurar_webhook_testes.Tenant.objects.get')
    def test_configures_authenticated_endpoint_and_checks_result(self, tenant, api, verify):
        tenant.return_value = self.tenant
        url = 'https://marcos.tacombinado.net/teste/receber/'
        api.side_effect = [None, {}, {'enabled': True, 'url': url, 'events': ['MESSAGES_UPSERT'],
            'headers': {'X-TestZap-Token': webhook_token(self.tenant)}}]
        output = StringIO()
        call_command('configurar_webhook_testes', tenant='marcos', stdout=output)
        verify.assert_called_once_with(url, self.tenant)
        payload = api.call_args_list[1].args[2]['webhook']
        self.assertEqual(payload['events'], ['MESSAGES_UPSERT'])
        self.assertFalse(payload['byEvents'])
        self.assertNotIn(webhook_token(self.tenant), output.getvalue())

    @patch('whatsapp.management.commands.configurar_webhook_testes.evolution.request')
    @patch('whatsapp.management.commands.configurar_webhook_testes.Tenant.objects.get')
    def test_other_integration_is_preserved(self, tenant, api):
        tenant.return_value = self.tenant
        api.return_value = {'enabled': True, 'url': 'https://other.example/webhook'}
        with self.assertRaisesMessage(CommandError, 'outra integração'):
            call_command('configurar_webhook_testes', tenant='marcos')
        api.assert_called_once()
