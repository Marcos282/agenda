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
