from datetime import time, timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.booking import reservar_por_whatsapp, cancelar, validar_limite_agendamentos
from usuarios.models import User
from profissionais.models import Profissional
from catalogo.models import ProfissionalServico
from agenda.models import Disponibilidade


class DailyBookingLimitTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()

    def test_two_bookings_then_friendly_error_other_date_and_cancellation(self):
        first = self.book()
        self.book(time(9,47))
        with self.assertRaisesMessage(ValidationError, f'o dia {self.day:%d/%m/%Y}'):
            self.book(time(10,27))
        validar_limite_agendamentos(tenant=self.tenant, whatsapp=self.user.whatsapp, dia=self.day + timedelta(days=1))
        with patch('django.utils.timezone.now', return_value=first.inicio - timedelta(minutes=1)):
            with self.assertRaisesMessage(ValidationError, 'para hoje'):
                self.book(time(10,27))
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=first.pk)
        self.book(time(10,27))

    def test_identity_combines_accounts_contacts_professionals_and_phone_formats(self):
        self.book()
        self.second.whatsapp = self.user.whatsapp
        self.second.save()
        self.book(time(9,47), cliente=self.second)
        other_prof = Profissional.objects.create(tenant=self.tenant, nome='Outro')
        offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=other_prof,
            servico=self.service, valor='40.00', duracao_minutos=40)
        Disponibilidade.objects.create(tenant=self.tenant, profissional=other_prof,
            data=self.day, hora_inicio=time(9), hora_fim=time(12))
        with self.assertRaisesMessage(ValidationError, 'limite de agendamentos'):
            reservar_por_whatsapp(tenant=self.tenant, nome='Outro nome', whatsapp='(11) 99999-1234',
                oferta_id=offer.pk, dia=self.day, hora=time(10), valor_exibido='40.00', duracao_exibida=40)
        validar_limite_agendamentos(tenant=self.other, whatsapp=self.user.whatsapp, dia=self.day)
        # Changing the account number must not erase the reservation's original identity.
        self.user.whatsapp = '+5511988881234'
        self.user.save()
        with self.assertRaises(ValidationError):
            validar_limite_agendamentos(tenant=self.tenant, whatsapp='11999991234', dia=self.day)

    def test_past_attendance_and_no_show_count_toward_that_date(self):
        first = self.book()
        second = self.book(time(9,47))
        from agenda.booking import registrar_falta
        admin = User.objects.create_user('no-show-limit-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        with patch('django.utils.timezone.now', return_value=second.inicio + timedelta(minutes=1)):
            registrar_falta(tenant=self.tenant, administrador=admin, agendamento_id=first.pk)
            with self.assertRaisesMessage(ValidationError, 'para hoje'):
                self.book(time(10,27))

    def test_limit_one_blocks_same_number_other_name_service_and_professional(self):
        from catalogo.models import Servico
        self.tenant.limite_agendamentos_cliente_dia = 1
        self.tenant.save(update_fields=['limite_agendamentos_cliente_dia'])
        first = reservar_por_whatsapp(tenant=self.tenant, nome='Primeiro nome', whatsapp='(11) 99999-1234',
            oferta_id=self.offer.pk, dia=self.day, hora=time(9,7), valor_exibido='40.00', duracao_exibida=40)
        other_prof = Profissional.objects.create(tenant=self.tenant, nome='Outro profissional')
        service = Servico.objects.create(tenant=self.tenant, nome='Outro serviço')
        offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=other_prof,
            servico=service, valor='50.00', duracao_minutos=30)
        next_day = self.day + timedelta(days=1)
        for day in [self.day, next_day]:
            Disponibilidade.objects.create(tenant=self.tenant, profissional=other_prof,
                data=day, hora_inicio=time(9), hora_fim=time(12))
        args = dict(tenant=self.tenant, nome='Nome diferente', whatsapp='+55 (11) 99999-1234',
            oferta_id=offer.pk, dia=self.day, hora=time(10), valor_exibido='50.00', duracao_exibida=30)
        with self.assertRaisesMessage(ValidationError, 'limite de agendamentos'):
            reservar_por_whatsapp(**args)
        # A password account with the same number also shares the limit.
        with self.assertRaises(ValidationError):
            self.book(time(10,27))
        args['dia'] = next_day
        reservar_por_whatsapp(**args)
        # Cancellation releases the same date without affecting other dates.
        cancelar(tenant=self.tenant, cliente=None, agendamento_id=first.pk)
        args['dia'] = self.day
        reservar_por_whatsapp(**args)

    def test_public_error_is_shown_to_customer(self):
        self.book()
        reservar_por_whatsapp(tenant=self.tenant, nome='Cliente', whatsapp=self.user.whatsapp,
            oferta_id=self.offer.pk, dia=self.day, hora=time(9,47), valor_exibido='40.00', duracao_exibida=40)
        response = self.client.post(self.slots_url(), self.payload(hora='10:27'), HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'Infelizmente, você já atingiu o limite', status_code=409)

    def test_admin_setting_is_independent_validated_and_applied(self):
        admin = User.objects.create_user('daily-limit-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        url = reverse('painel:meu_cadastro')
        response = self.client.post(url, {'acao': 'limite_agendamentos', 'limite_agendamentos_cliente_dia': 1}, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.limite_agendamentos_cliente_dia, 1)
        self.book()
        with self.assertRaises(ValidationError):
            self.book(time(9,47))
        for value in [0, -1, 'abc']:
            response = self.client.post(url, {'acao': 'limite_agendamentos', 'limite_agendamentos_cliente_dia': value}, HTTP_HOST='marcos.localhost')
            self.assertTrue(response.context['limite_form'].errors)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, {'acao': 'limite_agendamentos', 'limite_agendamentos_cliente_dia': 9}, HTTP_HOST='marcos.localhost').status_code, 403)
