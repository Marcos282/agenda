from unittest.mock import patch
from django.test import TestCase, override_settings
from agenda.test_booking import BookingFixture
from usuarios.models import User
from . import evolution


@override_settings(TENANT_BASE_DOMAIN='localhost')
class ConsoleTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('console@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)

    @patch('whatsapp.console.get_provider')
    def test_send_normalizes_and_uses_current_tenant(self, provider):
        response = self.client.post('/testezap', {'whatsapp': '(21) 99092-1092', 'mensagem': 'Teste'}, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        provider.return_value.send_text.assert_called_once_with(self.tenant, '+5521990921092', 'Teste')

    @patch('whatsapp.console.get_provider')
    def test_invalid_number_never_sends(self, provider):
        response = self.client.post('/testezap', {'whatsapp': 'abc', 'mensagem': 'Teste'}, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 200)
        provider.assert_not_called()

    @patch('whatsapp.console.evolution.find_messages', return_value=[{'text': 'Resposta', 'sent': False}])
    def test_receive_and_tenant_boundary(self, find):
        response = self.client.get('/testezap', {'mensagens': '1', 'whatsapp': '5521990921092'}, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.json()['messages'][0]['text'], 'Resposta')
        find.assert_called_once_with(self.tenant, '+5521990921092')
        self.assertEqual(self.client.get('/testezap', HTTP_HOST='wanessa.localhost').status_code, 403)

    @patch('whatsapp.evolution.request')
    def test_receive_filters_other_conversations(self, request):
        request.return_value = {'messages': {'records': [
            {'key': {'remoteJid': '5521990921092@s.whatsapp.net', 'fromMe': False}, 'message': {'conversation': 'Olá'}},
            {'key': {'remoteJid': '5511999999999@s.whatsapp.net'}, 'message': {'conversation': 'Privado'}},
        ]}}
        self.assertEqual(evolution.find_messages(self.tenant, '+5521990921092'), [{'text': 'Olá', 'sent': False}])

    def test_no_registration_controls(self):
        response = self.client.get('/testezap', HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'Enviar mensagem')
        self.assertNotContains(response, 'Conectar / gerar QR code')


@override_settings(WHATSAPP_TESTS_PIN='1031')
class ProtectedConsoleTests(ConsoleTests):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def unlock(self):
        return self.client.post('/testes', {'pin': '1031'}, HTTP_HOST='marcos.localhost')

    @patch('whatsapp.console.get_provider')
    def test_pin_blocks_sending_and_reading(self, provider):
        response = self.client.post('/testes', {'whatsapp': '5521990921092', 'mensagem': 'Teste'}, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'PIN de acesso')
        provider.assert_not_called()
        self.assertEqual(self.client.get('/testes?mensagens=1', HTTP_HOST='marcos.localhost').status_code, 403)
        self.assertEqual(self.client.get('/testes?diagnostico=1', HTTP_HOST='marcos.localhost').status_code, 403)

    @patch('whatsapp.console.get_provider')
    def test_unlock_send_and_lock(self, provider):
        self.assertEqual(self.unlock().status_code, 302)
        response = self.client.post('/testes', {'whatsapp': '5521990921092', 'mensagem': 'Teste'}, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.url, '/testes')
        provider.return_value.send_text.assert_called_once_with(self.tenant, '+5521990921092', 'Teste')
        self.client.post('/testes', {'acao': 'bloquear'}, HTTP_HOST='marcos.localhost')
        self.assertEqual(self.client.get('/testes?diagnostico=1', HTTP_HOST='marcos.localhost').status_code, 403)

    @patch('whatsapp.console.evolution.connection_info', return_value={'state': 'open', 'number': '+5521990921092'})
    @patch('whatsapp.console.evolution.configured', return_value=True)
    def test_diagnostics(self, configured, connection):
        self.unlock()
        response = self.client.get('/testes?diagnostico=1', HTTP_HOST='marcos.localhost')
        self.assertEqual(response.json()['status'], 'open')
        connection.assert_called_once_with(self.tenant)
        self.assertNotIn('apikey', response.content.decode())

    def test_wrong_pin_and_expiry(self):
        response = self.client.post('/testes', {'pin': '0000'}, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'PIN incorreto')
        self.unlock()
        session = self.client.session
        session['whatsapp_testes_access']['expires'] = 0
        session.save()
        self.assertEqual(self.client.get('/testes?diagnostico=1', HTTP_HOST='marcos.localhost').status_code, 403)

    @patch('whatsapp.console.evolution.find_messages')
    @patch('whatsapp.console.get_provider')
    def test_roundtrip_requires_matching_incoming_response(self, provider, find):
        provider.return_value.send_text.return_value = {'message_id': 'test-id'}
        self.unlock()
        self.client.post('/testes', {'acao': 'teste_completo', 'whatsapp': '5521990921092',
            'mensagem': 'Teste'}, HTTP_HOST='marcos.localhost')
        run = self.client.session['whatsapp_roundtrip']
        self.assertIn(run['token'], provider.return_value.send_text.call_args.args[2])
        find.return_value = [{'sent': True, 'text': run['token']}, {'sent': False, 'text': 'outra resposta'}]
        url = '/testes?mensagens=1&whatsapp=5521990921092'
        response = self.client.get(url, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.json()['test']['status'], 'aguardando_resposta')
        find.return_value = [{'sent': False, 'text': run['token']}]
        response = self.client.get(url, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.json()['test']['status'], 'confirmado')

    @patch('whatsapp.console.get_provider')
    def test_roundtrip_failure_is_reported(self, provider):
        provider.return_value.send_text.side_effect = evolution.EvolutionError('Conexão indisponível')
        self.unlock()
        response = self.client.post('/testes', {'acao': 'teste_completo', 'whatsapp': '5521990921092',
            'mensagem': 'Teste'}, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'Conexão indisponível')
        self.assertEqual(self.client.session['whatsapp_roundtrip']['status'], 'falha')
