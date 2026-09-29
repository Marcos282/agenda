from datetime import date, datetime, time, timezone
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from agenda.models import Disponibilidade
from agenda.services import configurar_dia, revisao_dia
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User


class OpeningTimeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        self.prof = Profissional.objects.create(nome='Profissional', tenant=self.tenant)
        self.admin = User.objects.create_user('opening@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.day = date(2026, 9, 29)
        # 10:30:20 in São Paulo. The current minute has already started.
        self.clock = patch('django.utils.timezone.now', return_value=datetime(2026, 9, 29, 13, 30, 20, tzinfo=timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def window(self, day=None, start=time(11), end=time(12), **kwargs):
        return Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof,
            data=day or self.day, hora_inicio=start, hora_fim=end, **kwargs)

    def configure(self, periods, day=None):
        day = day or self.day
        current = Disponibilidade.objects.filter(tenant=self.tenant, profissional=self.prof, data=day, ativo=True).order_by('hora_inicio', 'pk')
        configurar_dia(tenant=self.tenant, profissional_id=self.prof.pk, data=day,
            periodos=periods, revisao=revisao_dia(current))

    def test_past_date_rejected_but_elapsed_times_today_are_allowed(self):
        yesterday = self.day - date.resolution
        with self.assertRaisesMessage(ValidationError, 'data passada'):
            self.window(day=yesterday, start=time(9), end=time(12))
        with self.assertRaisesMessage(ValidationError, 'data passada'):
            self.configure([(time(9), time(12))], day=yesterday)
        self.configure([(time(9), time(10, 30))])
        self.window(day=self.day, start=time(10, 30), end=time(12))
        self.assertEqual(Disponibilidade.objects.count(), 2)

    def test_future_periods_and_timezone(self):
        self.configure([(time(9), time(11))])
        self.window(day=date(2026,9,30), start=time(0), end=time(1))
        self.assertEqual(Disponibilidade.objects.count(), 2)
        self.tenant.timezone = 'Asia/Tokyo'
        self.tenant.save()
        self.configure([(time(22,30), time(23))])

    def test_past_date_cannot_be_reopened(self):
        with patch('django.utils.timezone.now', return_value=datetime(2026,9,29,10,tzinfo=timezone.utc)):
            old = self.window(start=time(9))
        old.data = self.day - date.resolution
        with self.assertRaisesMessage(ValidationError, 'data passada'):
            old.save()
        old.refresh_from_db()
        self.assertEqual(old.data, self.day)

    def test_http_rejects_forged_past_opening_and_legacy_form(self):
        yesterday = self.day - date.resolution
        url = reverse('painel:agenda') + f'?profissional={self.prof.pk}&data={yesterday.isoformat()}'
        data = {'periodos-TOTAL_FORMS':'1', 'periodos-INITIAL_FORMS':'0', 'revisao':revisao_dia([]),
            'periodos-0-hora_inicio':'09:00', 'periodos-0-hora_fim':'12:00'}
        response = self.client.post(url, data, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'data passada', status_code=409)
        legacy = reverse('painel:disponibilidade_nova', args=[self.prof.pk])
        response = self.client.post(legacy, {'data':yesterday.isoformat(), 'hora_inicio':'09:00', 'hora_fim':'12:00', 'ativo':'on'}, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'data passada')
        self.assertFalse(Disponibilidade.objects.exists())
        past = self.client.get(url, HTTP_HOST='marcos.localhost')
        self.assertContains(past, 'Não é possível abrir a agenda em uma data passada.')
        self.assertNotContains(past, 'data-open-schedule')

    def test_agenda_uses_tenant_timezone_for_today(self):
        self.tenant.timezone = 'Asia/Tokyo'
        self.tenant.save()
        with patch('django.utils.timezone.now', return_value=datetime(2026, 9, 29, 23, 30, tzinfo=timezone.utc)):
            response = self.client.get(reverse('painel:agenda'), HTTP_HOST='marcos.localhost')
        self.assertEqual(response.context['dia'], date(2026, 9, 30))
        self.assertEqual(response.context['hoje'], '2026-09-30')
