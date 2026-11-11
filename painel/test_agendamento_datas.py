from datetime import date, time
from django.test import TestCase, override_settings
from django.urls import reverse
from agenda.models import Disponibilidade, Agendamento
from catalogo.models import Servico, ProfissionalServico
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
                   EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class BrazilianBookingDateTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Teste', subdomain='teste')
        self.prof = Profissional.objects.create(tenant=self.tenant, nome='Ana')
        service = Servico.objects.create(tenant=self.tenant, nome='Serviço')
        self.offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=self.prof,
            servico=service, valor='40.00', duracao_minutos=40)
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=date(2027, 10, 11),
            hora_inicio=time(8), hora_fim=time(12))
        admin = User.objects.create_user('dates@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        self.url = reverse('painel:agendamento_novo')

    def test_iso_url_renders_brazilian_date_without_inversion(self):
        response = self.client.get(self.url, {'profissional': self.prof.pk, 'data': '2027-10-11'}, HTTP_HOST='teste.localhost')
        self.assertContains(response, 'value="11/10/2027"')

    def test_brazilian_and_iso_posts_keep_confirmation_and_booking_date(self):
        for value, hour in [('11/10/2027', '08:00'), ('2027-10-11', '08:40')]:
            data = {'nome': 'Cliente', 'whatsapp': '11999991234', 'oferta': self.offer.pk,
                    'data': value, 'acao': 'consultar'}
            response = self.client.post(self.url, data, HTTP_HOST='teste.localhost')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['dia'], date(2027, 10, 11))
            data.update(acao='confirmar', hora=hour, cotacao=response.context['horario_form']['cotacao'].value())
            response = self.client.post(self.url, data, HTTP_HOST='teste.localhost')
            self.assertEqual(response.status_code, 302)
            self.assertIn('data=2027-10-11', response.url)
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_invalid_brazilian_date_is_rejected(self):
        response = self.client.post(self.url, {'nome': 'Cliente', 'whatsapp': '11999991234',
            'oferta': self.offer.pk, 'data': '31/02/2027', 'acao': 'consultar'}, HTTP_HOST='teste.localhost')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Agendamento.objects.exists())
