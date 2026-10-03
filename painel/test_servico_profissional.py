from datetime import time
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from agenda.test_booking import BookingFixture
from catalogo.models import ProfissionalServico
from profissionais.models import Profissional
from usuarios.models import User


class ProfessionalServiceAvailabilityTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('service-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.url = reverse('painel:vinculo_disponibilidade', args=[self.prof.pk, self.offer.pk])

    def post(self, acao):
        return self.client.post(self.url, {'acao': acao}, HTTP_HOST='marcos.localhost')

    def test_stop_offering_preserves_bookings_and_other_professionals(self):
        booking = self.book()
        other_prof = Profissional.objects.create(tenant=self.tenant, nome='Outro profissional')
        other_offer = ProfissionalServico.objects.create(tenant=self.tenant,
            profissional=other_prof, servico=self.service, valor='40.00', duracao_minutos=40)
        self.assertEqual(self.post('desativar').status_code, 302)
        self.offer.refresh_from_db()
        self.assertFalse(self.offer.ativo)
        self.assertTrue(ProfissionalServico.objects.disponiveis().filter(pk=other_offer.pk).exists())
        self.service.refresh_from_db()
        self.assertTrue(self.service.ativo)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CONFIRMADO')
        with self.assertRaises(ProfissionalServico.DoesNotExist):
            self.book(time(9,47))
        self.assertEqual(self.post('ativar').status_code, 302)
        self.book(time(9,47))

    def test_permissions_scope_csrf_and_post_only(self):
        self.assertEqual(self.client.get(self.url, HTTP_HOST='marcos.localhost').status_code, 405)
        self.assertEqual(self.post('invalid').status_code, 400)
        wrong_prof = Profissional.objects.create(tenant=self.tenant, nome='Outro')
        wrong_url = reverse('painel:vinculo_disponibilidade', args=[wrong_prof.pk, self.offer.pk])
        self.assertEqual(self.client.post(wrong_url, {'acao': 'desativar'}, HTTP_HOST='marcos.localhost').status_code, 404)
        foreign_prof = Profissional.objects.create(tenant=self.other, nome='Externo')
        foreign_url = reverse('painel:vinculo_disponibilidade', args=[foreign_prof.pk, self.offer.pk])
        self.assertEqual(self.client.post(foreign_url, {'acao': 'desativar'}, HTTP_HOST='marcos.localhost').status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, {'acao': 'desativar'}, HTTP_HOST='marcos.localhost').status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.post('desativar').status_code, 403)
        self.offer.refresh_from_db()
        self.assertTrue(self.offer.ativo)

    def test_inactive_catalog_service_cannot_be_reenabled(self):
        self.post('desativar')
        self.service.ativo = False
        self.service.save()
        self.assertEqual(self.post('ativar').status_code, 302)
        self.offer.refresh_from_db()
        self.assertFalse(self.offer.ativo)
