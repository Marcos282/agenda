from datetime import date, time, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User
from .models import Disponibilidade
from .services import configurar_dia, revisao_dia


class DailyAgendaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos', plano=Tenant.Plano.PROFISSIONAL)
        cls.other = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        cls.admin = User.objects.create_user('daily@example.test', 'Strong!Example_2026', tenant=cls.tenant, tipo='ADMIN')
        cls.prof = Profissional.objects.create(tenant=cls.tenant, nome='João')
        cls.sandro = Profissional.objects.create(tenant=cls.tenant, nome='Sandro')
        cls.foreign = Profissional.objects.create(tenant=cls.other, nome='Maria')
        cls.day = timezone.localdate() + timedelta(days=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, prof=None, day=None):
        return reverse('painel:agenda') + f'?profissional={(prof or self.prof).pk}&data={(day or self.day).isoformat()}'

    def get(self, url=None):
        return self.client.get(url or self.url(), HTTP_HOST='marcos.localhost')

    def window(self, start=9, end=12, **kwargs):
        return Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day,
                                             hora_inicio=time(start), hora_fim=time(end), **kwargs)

    def payload(self, pairs, revision=None):
        rows = list(Disponibilidade.objects.for_tenant(self.tenant).filter(profissional=self.prof, data=self.day, ativo=True).order_by('hora_inicio', 'pk'))
        result = {'periodos-TOTAL_FORMS': str(len(pairs)), 'periodos-INITIAL_FORMS': '0',
                  'revisao': revision if revision is not None else revisao_dia(rows)}
        for i, (start, end) in enumerate(pairs):
            result[f'periodos-{i}-hora_inicio'] = start
            result[f'periodos-{i}-hora_fim'] = end
        return result

    def post(self, data, url=None):
        return self.client.post(url or self.url(), data, HTTP_HOST='marcos.localhost')

    def test_closed_day_does_not_render_empty_timeline(self):
        response = self.get()
        self.assertFalse(response.context['aberta'])
        self.assertContains(response, 'Agenda fechada')
        self.assertContains(response, '+ Abrir agenda')
        self.assertNotContains(response, 'data-timeline aria-label')
        self.assertEqual(response.context['timeline']['windows'], [])

    def test_open_day_exact_periods_and_professional_status(self):
        self.window(); self.window(13, 18)
        response = self.get()
        self.assertTrue(response.context['aberta'])
        self.assertEqual(response.context['profissional'], self.prof)
        self.assertEqual(response.context['dia'], self.day)
        self.assertEqual([(w['start'], w['end']) for w in response.context['timeline']['windows']], [(32400,43200),(46800,64800)])
        status = {p.pk: p.tem_periodos for p in response.context['profissionais']}
        self.assertEqual(status, {self.prof.pk: True, self.sandro.pk: False})
        self.assertContains(response, 'Intervalo / fechado')
        self.assertEqual(response.context['timeline']['appointments'], [])

    def test_day_and_professional_switches_are_isolated(self):
        self.window()
        next_day = self.day + timedelta(days=1)
        for url in [self.url(day=next_day), self.url(prof=self.sandro)]:
            response = self.get(url)
            self.assertFalse(response.context['aberta'])
            self.assertEqual(response.context['periodos'], [])
        response = self.get(self.url(day=next_day))
        self.assertEqual(response.context['anterior'], (next_day - timedelta(days=1)).isoformat())
        self.assertEqual(response.context['proximo'], (next_day + timedelta(days=1)).isoformat())

    def test_inactive_professional_and_period_are_closed(self):
        self.window(ativo=False)
        self.assertFalse(self.get().context['aberta'])
        self.window()
        self.prof.ativo=False; self.prof.save()
        response=self.get()
        self.assertFalse(response.context['aberta'])
        self.assertEqual(response.context['timeline']['windows'], [])
        self.assertContains(response, 'Profissional inativo')
        self.assertNotContains(response, 'data-open-schedule href')

    def test_two_periods_saved_together_and_arbitrary_minutes_allowed(self):
        data=self.payload([('09:07','12:02'),('13:11','18:23')])
        data.update({'tenant_id':self.other.pk, 'profissional_id':self.foreign.pk, 'data':'2027-01-01'})
        response=self.post(data)
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        rows=list(Disponibilidade.objects.for_tenant(self.tenant).filter(profissional=self.prof))
        self.assertEqual(len(rows),2)
        self.assertTrue(all(p.data==self.day for p in rows))
        self.assertEqual(rows[0].hora_inicio,time(9,7))
        self.assertFalse(Disponibilidade.objects.filter(tenant=self.other).exists())

    def test_rejects_overlapping_zero_reverse_and_partial_rows_atomically(self):
        for pairs in [[('09:00','12:00'),('10:00','13:00')], [('09:00','09:00')], [('18:00','09:00')], [('09:00','12:00'),('13:00','')]]:
            with self.subTest(pairs=pairs):
                response=self.post(self.payload(pairs))
                self.assertEqual(response.status_code,400)
                self.assertTrue(response.context['configurando'])
                self.assertTrue(response.context['formset'].errors or response.context['formset'].non_form_errors())
                self.assertEqual(Disponibilidade.objects.count(),0)

    def test_adjacent_periods_valid(self):
        self.assertEqual(self.post(self.payload([('09:00','12:00'),('12:00','18:00')])).status_code,302)
        self.assertEqual(Disponibilidade.objects.count(),2)

    def test_edit_preserves_unchanged_id_and_deactivates_old_rows(self):
        first=self.window(); second=self.window(13,18)
        self.assertEqual(self.post(self.payload([('09:00','12:00'),('14:00','18:00')])).status_code,302)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertTrue(first.ativo); self.assertFalse(second.ativo)
        self.assertEqual(Disponibilidade.objects.count(),3)
        self.assertEqual(Disponibilidade.objects.filter(ativo=True).count(),2)

    def test_closing_day_preserves_other_dates_and_history(self):
        first=self.window()
        other=Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day + timedelta(days=1),hora_inicio=time(9),hora_fim=time(12))
        self.assertEqual(self.post(self.payload([])).status_code,302)
        first.refresh_from_db(); other.refresh_from_db()
        self.assertFalse(first.ativo); self.assertTrue(other.ativo)
        self.assertFalse(self.get().context['aberta'])

    def test_deleted_form_is_ignored(self):
        data=self.payload([('09:00','12:00'),('10:00','13:00')]); data['periodos-1-DELETE']='on'
        self.assertEqual(self.post(data).status_code,302)
        self.assertEqual(Disponibilidade.objects.count(),1)

    def test_stale_or_tampered_revision_does_not_overwrite(self):
        data=self.payload([('09:00','12:00')])
        self.window(13,18)
        self.assertEqual(self.post(data).status_code,409)
        self.assertEqual(self.post(self.payload([], revision='inválido')).status_code,409)
        self.assertEqual(Disponibilidade.objects.filter(ativo=True).count(),1)

    def test_failed_second_save_rolls_back_entire_replacement(self):
        original=self.window()
        real_create=Disponibilidade.objects.create
        calls=0
        def fail_second(**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:
                raise IntegrityError('simulated write failure')
            return real_create(**kwargs)
        with patch('agenda.services.Disponibilidade.objects.create',side_effect=fail_second):
            with self.assertRaises(IntegrityError):
                configurar_dia(tenant=self.tenant, profissional_id=self.prof.pk, data=self.day,
                               periodos=[(time(10),time(12)),(time(13),time(18))],revisao=revisao_dia([original]))
        original.refresh_from_db(); self.assertTrue(original.ativo)
        self.assertEqual(Disponibilidade.objects.count(),1)

    def test_foreign_professional_rejected_for_read_write_and_service(self):
        self.assertEqual(self.get(self.url(prof=self.foreign)).status_code,404)
        self.assertEqual(self.post(self.payload([('09:00','12:00')]),self.url(prof=self.foreign)).status_code,404)
        with self.assertRaises(Profissional.DoesNotExist):
            configurar_dia(tenant=self.tenant, profissional_id=self.foreign.pk,data=self.day,periodos=[],revisao='')
        self.assertNotContains(self.get(), 'Maria')

    def test_permissions_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.get().status_code,302)
        user=User.objects.create_user('professional@example.test','strongPassword123!',tenant=self.tenant,tipo='PROFISSIONAL')
        self.client.force_login(user)
        self.assertEqual(self.get().status_code,403)
        self.assertEqual(self.post(self.payload([])).status_code,403)
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(client.post(self.url(),self.payload([]),HTTP_HOST='marcos.localhost').status_code,403)

    def test_invalid_date_id_and_extreme_dates(self):
        for value in ['wrong','2026-02-31','']:
            self.assertEqual(self.get(reverse('painel:agenda')+'?data='+value).status_code,400)
        self.assertEqual(self.get(reverse('painel:agenda')+'?profissional=not-an-id').status_code,404)
        self.assertIsNone(self.get(self.url(day=date.min)).context['anterior'])
        self.assertIsNone(self.get(self.url(day=date.max)).context['proximo'])

    def test_no_professionals_and_today_in_tenant_timezone(self):
        from datetime import datetime, timezone as dt_timezone
        self.tenant.timezone='America/Sao_Paulo';self.tenant.save()
        with patch('django.utils.timezone.now',return_value=datetime.combine(self.day + timedelta(days=1), time(1), tzinfo=dt_timezone.utc)):
            self.assertEqual(self.get(reverse('painel:agenda')).context['dia'], self.day)
        self.prof.delete();self.sandro.delete()
        response=self.get(reverse('painel:agenda'))
        self.assertContains(response,'Cadastre seu primeiro profissional')

    def test_missing_management_data_and_too_many_rows_rejected(self):
        self.assertEqual(self.post({'revisao':revisao_dia([])}).status_code,400)
        data=self.payload([('09:00','10:00')]);data['periodos-TOTAL_FORMS']='100000'
        response=self.post(data)
        self.assertEqual(response.status_code,400)
        self.assertEqual(len(response.context['formset'].forms),100)

    def test_legacy_grade_unused_and_hidden(self):
        self.tenant.intervalo_grade_minutos=120;self.tenant.save()
        self.assertEqual(self.post(self.payload([('09:07','09:47')])).status_code,302)
        response=self.get()
        self.assertNotContains(response,'Grade de horários')
        self.assertNotContains(response,'intervalo_grade_minutos')
        self.assertEqual(response.context['timeline']['windows'][0]['start'],32820)
