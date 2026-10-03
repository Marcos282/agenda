from datetime import time
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.booking import reservar_por_whatsapp
from agenda.models import Agendamento
from usuarios.models import User, WhatsAppBloqueado


class WhatsAppBlockTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('block-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.url = reverse('painel:whatsapp_bloqueio', args=[self.user.whatsapp])

    def post(self, acao):
        return self.client.post(self.url, {'acao': acao}, HTTP_HOST='marcos.localhost')

    def test_block_account_and_public_contact_then_unblock(self):
        existing = self.book()
        self.assertEqual(self.post('bloquear').status_code, 302)
        self.assertEqual(self.post('bloquear').status_code, 302)
        self.assertEqual(WhatsAppBloqueado.objects.count(), 1)
        response = self.client.get(reverse('painel:clientes'), HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'Desbloquear agendamentos')
        with self.assertRaisesMessage(ValidationError, 'WhatsApp está bloqueado'):
            self.book(time(9,47))
        with self.assertRaisesMessage(ValidationError, 'WhatsApp está bloqueado'):
            reservar_por_whatsapp(tenant=self.tenant, nome='Outro nome', whatsapp='(11) 99999-1234',
                oferta_id=self.offer.pk, dia=self.day, hora=time(9,47),
                valor_exibido='40.00', duracao_exibida=40, acesso_publico=True)
        existing.refresh_from_db()
        self.assertEqual(existing.status, Agendamento.Status.CONFIRMADO)
        self.assertEqual(self.post('desbloquear').status_code, 302)
        self.book(time(9,47))

    def test_tenant_isolation_permissions_methods_and_csrf(self):
        WhatsAppBloqueado.objects.create(tenant=self.other, whatsapp=self.user.whatsapp)
        self.book()
        self.assertEqual(self.client.get(self.url, HTTP_HOST='marcos.localhost').status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, {'acao': 'bloquear'}, HTTP_HOST='marcos.localhost').status_code, 403)
        foreign_url = reverse('painel:whatsapp_bloqueio', args=['+5521999991234'])
        self.assertEqual(self.client.post(foreign_url, {'acao': 'bloquear'}, HTTP_HOST='marcos.localhost').status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.post('bloquear').status_code, 403)
        self.assertFalse(WhatsAppBloqueado.objects.filter(tenant=self.tenant).exists())
