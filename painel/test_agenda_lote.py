from datetime import timedelta, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone

from agenda.models import Disponibilidade
from agenda.services import configurar_dia
from catalogo.models import Servico, ProfissionalServico
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User


@override_settings(DEBUG=True, TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='', EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class BatchAgendaTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        self.other = Tenant.objects.create(nome='Outra', subdomain='outra')
        self.prof = Profissional.objects.create(tenant=self.tenant, nome='Ana')
        self.second = Profissional.objects.create(tenant=self.tenant, nome='Bia')
        self.inactive = Profissional.objects.create(tenant=self.tenant, nome='Inativo', ativo=False)
        self.foreign = Profissional.objects.create(tenant=self.other, nome='Outro tenant')
        self.admin = User.objects.create_user('batch@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.day = timezone.localdate(timezone=ZoneInfo(self.tenant.timezone)) + timedelta(days=2)
        self.url = reverse('painel:agenda') + '?lote=1'

    def data(self, count=7):
        return {'data_inicial': self.day.isoformat(), 'quantidade_dias': count,
            'profissionais': [str(self.prof.pk)],
            'datas': [(self.day + timedelta(days=i)).isoformat() for i in range(count)],
            'manha': 'on', 'manha_inicio': '08:00', 'manha_fim': '12:00',
            'tarde': 'on', 'tarde_inicio': '13:00', 'tarde_fim': '18:00', 'acao': 'prever_lote'}

    def post(self, data):
        return self.client.post(self.url, data, HTTP_HOST='marcos.localhost', HTTP_ACCEPT='application/json')

    def save(self, data, confirm=False):
        preview = self.post(data)
        self.assertEqual(preview.status_code, 200, preview.content)
        return self.post({**data, 'acao': 'salvar_lote', 'token': preview.json()['token'], 'confirmar': 'on' if confirm else ''})

    def test_default_seven_days_and_active_professionals_only(self):
        response = self.client.get(self.url, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['batch_days']), 7)
        self.assertEqual(len(response.context['batch_professionals']), 2)
        self.assertNotContains(response, 'Outro tenant')
        self.assertNotContains(response, 'Inativo')

    def test_navigation_keeps_selected_professional_and_future_date(self):
        response = self.client.get(self.url + f'&profissional={self.second.pk}&data={self.day.isoformat()}',
                                   HTTP_HOST='marcos.localhost')
        self.assertEqual(response.context['form']['data_inicial'].value(), self.day)
        self.assertEqual([row['object'].pk for row in response.context['batch_professionals'] if row['selected']], [self.second.pk])
        self.assertIn(f'profissional={self.second.pk}', response.context['batch_back_url'])
        self.assertIn(self.day.isoformat(), response.context['batch_back_url'])
        result = self.save(self.data(1)).json()
        self.assertIn(f'profissional={self.prof.pk}', result['agenda_url'])
        self.assertIn(self.day.isoformat(), result['agenda_url'])

    def test_one_and_seven_day_limits_create_exact_dates(self):
        for count in (1, 7):
            with self.subTest(count=count):
                data = self.data(count)
                response = self.save(data, confirm=True)
                self.assertEqual(response.status_code, 200, response.content)
                dates = set(Disponibilidade.objects.filter(ativo=True).values_list('data', flat=True))
                self.assertEqual(dates, {self.day + timedelta(days=i) for i in range(count)})

    def test_invalid_counts_rejected_by_backend(self):
        for count in (0, 8, -1, 'abc', '1.5', '', '999999999999999999999'):
            with self.subTest(count=count):
                data = self.data(1); data['quantidade_dias'] = count
                self.assertEqual(self.post(data).status_code, 400)
        self.assertFalse(Disponibilidade.objects.exists())

    def test_brazilian_date_display_and_legacy_iso_input_are_equivalent(self):
        response = self.client.get(self.url + '&data=2027-10-11', HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'value="11/10/2027"')
        for start in ('11/10/2027', '2027-10-11'):
            data = self.data(1)
            data.update(data_inicial=start, datas=['2027-10-11'])
            result = self.post(data)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['dates'], ['11/10/2027'])
        self.assertFalse(Disponibilidade.objects.exists())

    def test_invalid_brazilian_dates_are_rejected_without_day_rollover(self):
        for start in ('31/02/2027', '15/13/2027', '10/11/26'):
            data = self.data(1); data['data_inicial'] = start
            self.assertEqual(self.post(data).status_code, 400)

    def test_invalid_past_initial_and_out_of_range_dates_are_rejected(self):
        for start in ('invalid', '2026-02-30', (self.day - timedelta(days=10)).isoformat(), '9999-12-31'):
            data = self.data(); data['data_inicial'] = start
            self.assertEqual(self.post(data).status_code, 400)
        data = self.data(1); data['datas'] = [(self.day + timedelta(days=1)).isoformat()]
        self.assertEqual(self.post(data).status_code, 400)

    def test_only_checked_dates_and_selected_professionals_are_changed(self):
        data = self.data(); data['datas'] = [self.day.isoformat(), (self.day + timedelta(days=4)).isoformat()]
        self.assertEqual(self.save(data).status_code, 200)
        self.assertEqual(Disponibilidade.objects.count(), 4)
        self.assertFalse(Disponibilidade.objects.filter(profissional=self.second).exists())

    def test_empty_selections_foreign_and_inactive_professionals_are_rejected(self):
        for ids in ([], [str(self.foreign.pk)], [str(self.inactive.pk)], ['99999999999999999999999999999999']):
            data = self.data(); data['profissionais'] = ids
            self.assertEqual(self.post(data).status_code, 400)
        data = self.data(); data['datas'] = []
        self.assertEqual(self.post(data).status_code, 400)

    def test_overlap_empty_shifts_and_reversed_times_are_rejected(self):
        for changes in ({'manha_fim': '14:00'}, {'manha_inicio': '12:00'},
                        {'manha': '', 'tarde': ''}, {'manha_fim': ''}, {'manha_inicio': '08:00:01'}):
            self.assertEqual(self.post({**self.data(1), **changes}).status_code, 400)
        self.assertFalse(Disponibilidade.objects.exists())

    def test_preview_is_read_only_and_confirmation_is_required_for_existing_rows(self):
        original = Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
            hora_inicio=time(9), hora_fim=time(10))
        data = self.data(1)
        preview = self.post(data).json()
        self.assertEqual(preview['updated'], 1)
        self.assertEqual(Disponibilidade.objects.count(), 1)
        self.assertEqual(self.post({**data, 'acao': 'salvar_lote', 'token': preview['token']}).status_code, 409)
        original.refresh_from_db(); self.assertTrue(original.ativo)
        self.assertEqual(self.save(data, confirm=True).status_code, 200)

    def test_inactive_history_requires_confirmation_before_reopening_closed_day(self):
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
            hora_inicio=time(9), hora_fim=time(10), ativo=False)
        self.assertEqual(self.save(self.data(1)).status_code, 409)
        self.assertEqual(self.save(self.data(1), confirm=True).status_code, 200)

    def test_modified_selection_and_missing_or_stale_token_are_rejected(self):
        data = self.data(1)
        self.assertEqual(self.post({**data, 'acao': 'salvar_lote'}).status_code, 409)
        preview = self.post(data).json()
        self.assertEqual(self.post({**data, 'acao': 'salvar_lote', 'token': preview['token'], 'manha_inicio': '09:00'}).status_code, 409)
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
            hora_inicio=time(9), hora_fim=time(10))
        self.assertEqual(self.post({**data, 'acao': 'salvar_lote', 'token': preview['token'], 'confirmar': 'on'}).status_code, 409)

    def test_days_with_future_bookings_cannot_be_changed_even_with_confirmation(self):
        from agenda.booking import reservar_por_whatsapp
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
            hora_inicio=time(8), hora_fim=time(12))
        service = Servico.objects.create(tenant=self.tenant, nome='Corte')
        offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=self.prof, servico=service,
            valor='40.00', duracao_minutos=40)
        data = {**self.data(2), 'manha': ''}
        before_booking = self.post(data).json()
        booking = reservar_por_whatsapp(tenant=self.tenant, nome='Cliente', whatsapp='11999991234',
            oferta_id=offer.pk, dia=self.day, hora=time(10), valor_exibido='40.00', duracao_exibida=40)
        self.assertEqual(self.post({**data, 'acao': 'salvar_lote', 'token': before_booking['token'], 'confirmar': 'on'}).status_code, 409)
        before_periods = list(Disponibilidade.objects.order_by('pk').values())
        before_reservation = type(booking).objects.filter(pk=booking.pk).values().get()
        response = self.post(data)
        self.assertEqual(response.status_code, 409)
        self.assertIn('reservas futuras', response.content.decode())
        self.assertEqual(list(Disponibilidade.objects.order_by('pk').values()), before_periods)
        self.assertEqual(type(booking).objects.filter(pk=booking.pk).values().get(), before_reservation)
        # An unchanged booked day does not prevent opening a different empty day.
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
            hora_inicio=time(13), hora_fim=time(18))
        self.assertEqual(self.save(self.data(2)).status_code, 200)
        booking.refresh_from_db(); self.assertEqual(booking.status, 'CONFIRMADO')
        self.assertTrue(Disponibilidade.objects.filter(ativo=True, hora_inicio__lte=time(10), hora_fim__gte=time(10, 40)).exists())

    def test_batch_is_atomic_when_a_later_day_fails(self):
        calls = 0
        def configure(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValidationError('Falha de validação no segundo dia.')
            return configurar_dia(**kwargs)
        with patch('painel.agenda_lote.configurar_dia', side_effect=configure):
            self.assertEqual(self.save(self.data(2)).status_code, 409)
        self.assertFalse(Disponibilidade.objects.exists())

    def test_future_eight_am_booking_remains_visible_when_other_day_is_opened(self):
        from agenda.booking import reservar_por_whatsapp
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
            hora_inicio=time(8), hora_fim=time(12))
        service = Servico.objects.create(tenant=self.tenant, nome='Serviço às oito')
        offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=self.prof,
            servico=service, valor='40.00', duracao_minutos=40)
        booking = reservar_por_whatsapp(tenant=self.tenant, nome='Cliente das oito', whatsapp='11999991234',
            oferta_id=offer.pk, dia=self.day, hora=time(8), valor_exibido='40.00', duracao_exibida=40)
        self.assertEqual(self.post(self.data(1)).status_code, 409)
        data = self.data(1)
        other_day = (self.day + timedelta(days=1)).isoformat()
        data.update(data_inicial=other_day, datas=[other_day])
        self.assertEqual(self.save(data).status_code, 200)
        response = self.client.get(reverse('painel:agenda'),
            {'profissional': self.prof.pk, 'data': self.day.isoformat()}, HTTP_HOST='marcos.localhost')
        self.assertEqual([row['id'] for row in response.context['timeline']['appointments']], [booking.pk])
        self.assertContains(response, '08:00')
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CONFIRMADO')

    def test_permissions_csrf_and_cross_tenant_isolation(self):
        self.assertEqual(self.client.post(self.url, self.data(1), HTTP_HOST='outra.localhost').status_code, 403)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.admin)
        self.assertEqual(secure.post(self.url, self.data(1), HTTP_HOST='marcos.localhost').status_code, 403)
        staff = User.objects.create_user('staff-batch@example.test', tenant=self.tenant, tipo='PROFISSIONAL')
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url, HTTP_HOST='marcos.localhost').status_code, 403)
        self.client.logout(); self.assertEqual(self.client.get(self.url, HTTP_HOST='marcos.localhost').status_code, 302)
