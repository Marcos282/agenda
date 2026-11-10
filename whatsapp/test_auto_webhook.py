from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, RequestFactory, Client, override_settings
from django.urls import reverse

from tenants.models import Tenant
from usuarios.models import User
from . import evolution
from .models import Configuracao
from .reply_views import webhook_token
from .webhooks import ensure_webhook, WebhookSetupError


@override_settings(STORE_BASE_DOMAIN='tacombinado.net', EVOLUTION_INSTANCE_PREFIX='test_tenant')
class AutoWebhookServiceTests(SimpleTestCase):
    def setUp(self):
        self.tenant = SimpleNamespace(pk=15, subdomain='nova-loja')
        self.target = 'https://nova-loja.tacombinado.net/whatsapp/respostas/'
        self.ready = {'url': self.target, 'enabled': True, 'events': ['MESSAGES_UPSERT'],
                      'headers': {'X-Agendamento-Token': webhook_token(self.tenant)}}

    @patch('whatsapp.evolution.request')
    def test_new_instance_is_configured_and_verified(self, api):
        api.side_effect = [None, {}, self.ready]
        self.assertTrue(ensure_webhook(self.tenant))
        self.assertEqual(api.call_args_list[0].args, ('GET', '/webhook/find/test_tenant_15'))
        payload = api.call_args_list[1].args[2]['webhook']
        self.assertEqual(payload['url'], self.target)
        self.assertEqual(payload['headers'], self.ready['headers'])
        self.assertFalse(payload['byEvents'])
        self.assertFalse(payload['base64'])

    @patch('whatsapp.evolution.request')
    def test_correct_config_is_read_only_even_on_repeated_attempts(self, api):
        api.return_value = self.ready
        self.assertFalse(ensure_webhook(self.tenant))
        self.assertFalse(ensure_webhook(self.tenant))
        self.assertEqual([call.args[0] for call in api.call_args_list], ['GET', 'GET'])

    @patch('whatsapp.evolution.request')
    def test_new_webhook_with_null_fields_is_configured(self, api):
        api.side_effect = [{'url': None, 'headers': None, 'events': None}, {}, self.ready]
        self.assertTrue(ensure_webhook(self.tenant))

    @patch('whatsapp.evolution.request')
    def test_header_case_is_ignored(self, api):
        api.return_value = {**self.ready, 'headers': {'x-agendamento-token': webhook_token(self.tenant)}}
        self.assertFalse(ensure_webhook(self.tenant))
        api.assert_called_once()

    @patch('whatsapp.evolution.request')
    def test_events_headers_and_existing_inbox_are_preserved(self, api):
        from .inbox_views import webhook_token as inbox_token
        target = 'https://nova-loja.tacombinado.net/teste/receber/'
        previous = {'url': target, 'events': ['CONNECTION_UPDATE'], 'headers': {'X-Custom': 'keep'}}
        updated = {**self.ready, 'url': target, 'events': ['CONNECTION_UPDATE', 'MESSAGES_UPSERT'],
            'headers': {**self.ready['headers'], 'X-Custom': 'keep', 'X-TestZap-Token': inbox_token(self.tenant)}}
        api.side_effect = [previous, {}, updated]
        ensure_webhook(self.tenant)
        payload = api.call_args_list[1].args[2]['webhook']
        self.assertEqual(payload['url'], target)
        self.assertEqual(payload['events'], updated['events'])
        self.assertEqual(payload['headers'], updated['headers'])

    @patch('whatsapp.evolution.request')
    def test_foreign_tenant_or_unknown_integration_is_never_overwritten(self, api):
        for url in ('https://other.example/webhook',
                    'https://outro.tacombinado.net/whatsapp/respostas/',
                    'https://nova-loja.tacombinado.net/unknown',
                    self.target + '?token=other', self.target + '#other'):
            with self.subTest(url=url):
                api.reset_mock(); api.return_value = {'url': url}
                with self.assertRaises(WebhookSetupError):
                    ensure_webhook(self.tenant)
                api.assert_called_once()

    @patch('whatsapp.evolution.request')
    def test_rotated_token_replaces_old_case_insensitively(self, api):
        api.side_effect = [{**self.ready, 'headers': {'x-agendamento-token': 'old'}}, {}, self.ready]
        ensure_webhook(self.tenant)
        self.assertEqual(api.call_args_list[1].args[2]['webhook']['headers'], self.ready['headers'])

    @patch('whatsapp.evolution.request')
    def test_disabled_or_by_events_config_is_repaired(self, api):
        api.side_effect = [{**self.ready, 'enabled': False, 'webhookByEvents': True}, {}, self.ready]
        self.assertTrue(ensure_webhook(self.tenant))

    @patch('whatsapp.evolution.request')
    def test_missing_verification_is_not_reported_as_success(self, api):
        api.side_effect = [None, {}, None]
        with self.assertRaises(WebhookSetupError):
            ensure_webhook(self.tenant)

    @patch('whatsapp.evolution.request')
    def test_read_only_mode_does_not_write(self, api):
        api.return_value = None
        self.assertFalse(ensure_webhook(self.tenant, apply=False))
        api.assert_called_once()

    @patch('whatsapp.evolution.request')
    def test_localhost_cannot_point_at_production_callback_automatically(self, api):
        request = RequestFactory().get('/', HTTP_HOST='nova-loja.localhost')
        with override_settings(ALLOWED_HOSTS=['.localhost']):
            with self.assertRaises(WebhookSetupError):
                ensure_webhook(self.tenant, request=request)
        api.assert_not_called()

    @patch('whatsapp.evolution.request')
    def test_other_tenant_token_does_not_count_as_ready(self, api):
        other = SimpleNamespace(pk=99)
        api.side_effect = [{**self.ready, 'headers': {'X-Agendamento-Token': webhook_token(other)}}, {}, self.ready]
        self.assertTrue(ensure_webhook(self.tenant))


@override_settings(DEBUG=False, TENANT_BASE_DOMAIN='tacombinado.net', STORE_BASE_DOMAIN='tacombinado.net',
    ALLOWED_HOSTS=['.tacombinado.net', 'tacombinado.net'], EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class AutoWebhookPanelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Nova loja', subdomain='nova-loja')
        self.other = Tenant.objects.create(nome='Outra loja', subdomain='outra')
        self.admin = User.objects.create_user('autohook@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.api = patch('whatsapp.evolution.request').start()
        self.info = patch('whatsapp.evolution.connection_info', return_value={'state': 'open', 'number': ''}).start()
        patch('whatsapp.evolution.configured', return_value=True).start()
        self.connect = patch('whatsapp.evolution.connect', return_value='').start()
        self.addCleanup(patch.stopall)
        self.ready = {'url': 'https://nova-loja.tacombinado.net/whatsapp/respostas/', 'enabled': True,
            'events': ['MESSAGES_UPSERT'], 'headers': {'X-Agendamento-Token': webhook_token(self.tenant)}}

    def post(self, action):
        return self.client.post(reverse('painel:whatsapp'), {'acao': action},
                                HTTP_HOST='nova-loja.tacombinado.net', secure=True)

    def test_connect_sets_up_new_tenant_without_enabling_features(self):
        self.api.side_effect = [None, {}, self.ready]
        response = self.post('conectar')
        self.assertContains(response, 'Recebimento de respostas configurado.')
        self.connect.assert_called_once_with(self.tenant)
        config = Configuracao.objects.get(tenant=self.tenant)
        self.assertFalse(config.confirmar_presenca_whatsapp)
        self.assertFalse(config.cancelar_whatsapp)
        self.assertFalse(config.lembretes_ativos)
        self.assertNotContains(response, webhook_token(self.tenant))

    def test_verify_repairs_existing_tenant_and_is_idempotent(self):
        self.api.side_effect = [None, {}, self.ready, self.ready]
        self.assertTrue(self.post('verificar').context['receiving']['ready'])
        self.assertTrue(self.post('verificar').context['receiving']['ready'])
        self.assertEqual([call.args[0] for call in self.api.call_args_list], ['GET', 'POST', 'GET', 'GET'])

    def test_failure_preserves_connection_and_retry_succeeds(self):
        self.api.side_effect = evolution.EvolutionError('private-diagnostic')
        response = self.post('conectar')
        self.assertEqual(response.context['connection']['kind'], 'online')
        self.assertContains(response, 'Tentar configurar recebimento novamente')
        self.assertNotContains(response, 'private-diagnostic')
        self.api.side_effect = [None, {}, self.ready]
        self.assertTrue(self.post('configurar_recebimento').context['receiving']['ready'])
        self.assertEqual(self.connect.call_count, 1)

    def test_foreign_integration_is_preserved_and_explained(self):
        self.api.return_value = {'url': 'https://other.example/hook'}
        response = self.post('verificar')
        self.assertContains(response, 'outra integração')
        self.assertFalse(response.context['receiving']['ready'])
        self.api.assert_called_once()

    def test_setup_failure_does_not_hide_pairing_qrcode(self):
        self.connect.return_value = 'data:image/png;base64,test'
        self.info.return_value = {'state': 'connecting', 'number': ''}
        self.api.side_effect = evolution.EvolutionError('unavailable')
        response = self.post('conectar')
        self.assertEqual(response.context['qr'], 'data:image/png;base64,test')
        self.assertContains(response, 'QR code para conectar')
        self.assertContains(response, 'Tentar configurar recebimento novamente')

    def test_get_does_not_modify_or_configure_webhook(self):
        self.client.get(reverse('painel:whatsapp'), HTTP_HOST='nova-loja.tacombinado.net', secure=True)
        self.api.assert_not_called()

    def test_disconnect_does_not_reconfigure(self):
        self.post('desconectar')
        self.api.assert_called_once_with('DELETE', '/instance/logout/' + evolution.instance(self.tenant))

    def test_cross_tenant_unauthenticated_and_csrf_requests_cannot_configure(self):
        response = self.client.post(reverse('painel:whatsapp'), {'acao': 'configurar_recebimento'},
                                    HTTP_HOST='outra.tacombinado.net', secure=True)
        self.assertEqual(response.status_code, 403)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.admin)
        self.assertEqual(secure.post(reverse('painel:whatsapp'), {'acao': 'configurar_recebimento'},
            HTTP_HOST='nova-loja.tacombinado.net', secure=True).status_code, 403)
        self.client.logout()
        self.assertEqual(self.post('conectar').status_code, 302)
        self.api.assert_not_called()
