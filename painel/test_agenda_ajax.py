from django.test import TestCase, override_settings
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.booking import cancelar
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost')
class AgendaAjaxTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('ajax-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.url = reverse('painel:agenda_dados')
        self.params = {'profissional':self.prof.pk, 'data':self.day.isoformat()}

    def load(self, **params):
        return self.client.get(self.url, dict(self.params, **params), HTTP_HOST='marcos.localhost')

    def test_dynamic_new_and_cancelled_reservations(self):
        first = self.load()
        self.assertEqual(first.status_code, 200)
        self.assertIn('no-store', first.headers['Cache-Control'])
        self.assertEqual(first.json()['timeline']['appointments'], [])
        booking = self.book()
        data = self.load().json()
        self.assertEqual(data['timeline']['appointments'][0]['id'], booking.pk)
        self.assertIn('Cliente Teste', data['resumo_html'])
        self.assertIn('Cliente Novo', data['resumo_html'])
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=booking.pk)
        self.assertEqual(self.load().json()['timeline']['appointments'], [])

    def test_scope_invalid_parameters_and_post_only_read(self):
        from profissionais.models import Profissional
        external = Profissional.objects.create(tenant=self.other, nome='Externo')
        self.assertEqual(self.load(profissional=external.pk).status_code,404)
        self.assertEqual(self.load(data='invalid').status_code,400)
        self.assertEqual(self.load(profissional='9999999999999999999999').status_code,404)
        self.assertEqual(self.client.post(self.url, self.params, HTTP_HOST='marcos.localhost').status_code,405)
        pro = User.objects.create_user('ajax-professional@example.test',tenant=self.tenant,tipo='PROFISSIONAL')
        self.client.force_login(pro)
        self.assertEqual(self.load().status_code,403)
        self.client.logout()
        self.assertEqual(self.load().status_code,302)

    def test_closed_and_inactive_agenda_keep_history(self):
        booking = self.book()
        self.prof.ativo = False
        self.prof.save()
        data = self.load().json()
        self.assertFalse(data['aberta'])
        self.assertEqual(data['timeline']['windows'],[])
        self.assertEqual(data['timeline']['appointments'][0]['id'],booking.pk)

    def test_page_has_ajax_url_for_open_and_closed_days(self):
        from datetime import timedelta
        for day in [self.day,self.day+timedelta(days=1)]:
            response=self.client.get(reverse('painel:agenda'),{'profissional':self.prof.pk,'data':day.isoformat()},HTTP_HOST='marcos.localhost')
            self.assertContains(response,'data-agenda-refresh')
            self.assertContains(response,self.url)
            self.assertContains(response,'data-timeline')
