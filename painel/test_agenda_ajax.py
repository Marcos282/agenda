from datetime import time
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
        self.assertIn('redirect_url', data)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CONFIRMADO')

    def test_page_has_ajax_url_for_open_and_closed_days(self):
        from datetime import timedelta
        for day in [self.day,self.day+timedelta(days=1)]:
            response=self.client.get(reverse('painel:agenda'),{'profissional':self.prof.pk,'data':day.isoformat()},HTTP_HOST='marcos.localhost')
            self.assertContains(response,'data-agenda-refresh')
            self.assertContains(response,self.url)
            self.assertContains(response,'data-timeline')

    def test_page_accepts_whitespace_around_date_parameter(self):
        response = self.client.get(
            reverse('painel:agenda'),
            {'profissional': self.prof.pk, 'data': f' {self.day.isoformat()} '},
            HTTP_HOST='marcos.localhost',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dia'], self.day)

    def set_active(self, active):
        data = {'nome': self.prof.nome}
        if active:
            data['ativo'] = 'on'
        response = self.client.post(reverse('painel:profissional_editar', args=[self.prof.pk]),
                                    data, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.ativo, active)

    def test_checkbox_lifecycle_preserves_bookings_windows_and_services(self):
        from agenda.booking import horarios_disponiveis
        from agenda.models import Agendamento, Disponibilidade
        from catalogo.models import ProfissionalServico
        from painel.agendamento_views import AgendamentoPainelForm
        booking = self.book()
        snapshots = {model: list(model.objects.order_by('pk').values())
                     for model in [Agendamento, Disponibilidade, ProfissionalServico]}
        def assert_available(active):
            response = self.client.get(reverse('painel:agenda'), {'data': self.day.isoformat()},
                                       HTTP_HOST='marcos.localhost')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(list(response.context['profissionais']), [self.prof] if active else [])
            self.assertEqual(response.context['aberta'], active)
            if active:
                self.assertEqual(response.context['timeline']['appointments'][0]['id'], booking.pk)
            else:
                self.assertContains(response, 'Nenhum profissional ativo')
                self.assertNotContains(response, 'data-open-schedule')
            form = AgendamentoPainelForm(tenant=self.tenant)
            self.assertEqual(form.fields['oferta'].queryset.filter(pk=self.offer.pk).exists(), active)
            self.assertEqual(bool(horarios_disponiveis(self.offer, self.day)), active)
            public = self.client.get(reverse('home'), HTTP_HOST='marcos.localhost')
            self.assertEqual(self.prof in public.context['equipe'], active)
            for url in [self.slots_url(), reverse('agenda:horarios_atualizar',
                         args=[self.offer.pk, self.day.isoformat()])]:
                self.assertEqual(self.client.get(url, HTTP_HOST='marcos.localhost').status_code,
                                 200 if active else 404)
        assert_available(True)
        self.set_active(False)
        assert_available(False)
        response = self.client.get(reverse('painel:agenda'), self.params,
                                   HTTP_HOST='marcos.localhost', follow=True)
        self.assertContains(response, 'Nenhum profissional ativo')
        self.assertEqual(response.context['dia'], self.day)
        self.assertIsNone(response.context['profissional'])
        self.assertEqual(self.client.get(reverse('home_profissional', args=[self.prof.pk]),
                                        HTTP_HOST='marcos.localhost').status_code, 404)
        with self.assertRaises(ProfissionalServico.DoesNotExist):
            self.book(hora=time(10, 30))
        response = self.client.post(reverse('painel:agendamento_novo'), {
            'nome': 'Novo cliente', 'whatsapp': '(11) 99999-1234', 'oferta': self.offer.pk,
            'data': self.day.isoformat(), 'acao': 'consultar'}, HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 400)
        self.assertIn('oferta', response.context['form'].errors)
        for model, before in snapshots.items():
            self.assertEqual(list(model.objects.order_by('pk').values()), before)
        self.set_active(True)
        assert_available(True)
        for model, before in snapshots.items():
            self.assertEqual(list(model.objects.order_by('pk').values()), before)
        self.assertEqual(self.load().json()['timeline']['appointments'][0]['id'], booking.pk)
        self.assertTrue(self.book(hora=time(10, 30)).pk)

    def test_inactive_urls_select_active_tenant_professional_without_applying_post(self):
        from profissionais.models import Profissional
        from agenda.models import Disponibilidade
        replacement = Profissional.objects.create(tenant=self.tenant, nome='Outra profissional')
        foreign = Profissional.objects.create(tenant=self.other, nome='Outro estabelecimento')
        self.set_active(False)
        from .agenda_views import agenda_url
        target = agenda_url(replacement.pk, self.day)
        params = {'profissional': self.prof.pk, 'data': self.day.isoformat()}
        url = reverse('painel:agenda')
        response = self.client.get(url, params, HTTP_HOST='marcos.localhost')
        self.assertRedirects(response, target, fetch_redirect_response=False)
        legacy = reverse('painel:disponibilidades', args=[self.prof.pk])
        self.assertRedirects(self.client.get(legacy, {'data': self.day.isoformat()},
                             HTTP_HOST='marcos.localhost'), target, fetch_redirect_response=False)
        before = list(Disponibilidade.objects.values())
        self.assertRedirects(self.client.post(url + '?profissional=' + str(self.prof.pk) +
                             '&data=' + self.day.isoformat(), {}, HTTP_HOST='marcos.localhost'),
                             target, fetch_redirect_response=False)
        self.assertEqual(before, list(Disponibilidade.objects.values()))
        self.assertEqual(self.load().json(), {'redirect_url': target})
        self.assertEqual(self.load(profissional=foreign.pk).status_code, 404)
        self.assertEqual(self.client.get(url, {**params, 'profissional': foreign.pk},
                                        HTTP_HOST='marcos.localhost').status_code, 404)
