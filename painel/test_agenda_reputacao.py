from datetime import time, timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from agenda.models import ReputacaoCliente
from agenda.test_booking import BookingFixture
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost')
class AgendaReputationTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('rating-ajax@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)

    def post_rating(self, booking, action, host='marcos.localhost'):
        return self.client.post(reverse('painel:agendamento_' + action, args=[booking.pk]),
                                HTTP_HOST=host, HTTP_ACCEPT='application/json')

    def test_late_persisted_removed_after_reload_other_booking_kept(self):
        booking = self.book()
        other = self.book(time(9,47), cliente=self.second)
        params = {'profissional': self.prof.pk, 'data': self.day.isoformat()}
        with patch('django.utils.timezone.now', return_value=booking.inicio):
            before = self.client.get(reverse('painel:agenda'), params, HTTP_HOST='marcos.localhost')
            self.assertContains(before, f'data-rating-row="{booking.pk}"')
            self.assertEqual(self.post_rating(booking, 'atraso').json()['ok'], True)
            # Even a different repeated action cannot overwrite the first outcome.
            self.assertEqual(self.post_rating(booking, 'falta').json()['tipo'], 'ATRASADO')
            for url in ['painel:agenda', 'painel:agenda_dados']:
                response = self.client.get(reverse(url), params, HTTP_HOST='marcos.localhost')
                timeline = response.context['timeline'] if url == 'painel:agenda' else response.json()['timeline']
                self.assertEqual([a['id'] for a in timeline['pendingAppointments']], [other.pk])
                self.assertEqual([a['id'] for a in timeline['appointments']], [booking.pk, other.pk])
                html = response.content.decode() if url == 'painel:agenda' else response.json()['resumo_html']
                self.assertNotIn(f'data-rating-row="{booking.pk}"', html)
                self.assertIn(f'data-rating-row="{other.pk}"', html)
        rating = ReputacaoCliente.objects.get(agendamento=booking)
        self.assertEqual(rating.pontuacao, 3)
        self.assertEqual(rating.tenant, self.tenant)
        self.assertFalse(ReputacaoCliente.objects.filter(agendamento=other).exists())
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CONFIRMADO')

    def test_actions_and_duplicates(self):
        for hour, action, kind in [(time(9,7), 'cancelar', 'DESMARCOU'), (time(9,47), 'falta', 'AUSENTE'), (time(10,27), 'concluir', 'CONCLUIDO')]:
            with self.subTest(action=action):
                booking = self.book(hour, cliente=self.second if action == 'falta' else self.user)
                moment = booking.inicio - timedelta(seconds=1) if action == 'cancelar' else booking.fim
                with patch('django.utils.timezone.now', return_value=moment):
                    first = self.post_rating(booking, action)
                    second = self.post_rating(booking, action)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.json(), first.json())
                self.assertEqual(ReputacaoCliente.objects.filter(agendamento=booking).count(), 1)
                self.assertEqual(first.json()['tipo'], kind)
    def test_error_and_tenant_isolation(self):
        booking = self.book()
        response = self.post_rating(booking, 'atraso')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()['ok'])
        self.assertFalse(ReputacaoCliente.objects.exists())
        foreign_admin = User.objects.create_user('foreign-rating-ajax@example.test', tenant=self.other, tipo='ADMIN')
        self.client.force_login(foreign_admin)
        self.assertEqual(self.post_rating(booking, 'atraso', 'wanessa.localhost').status_code, 404)
        self.assertFalse(ReputacaoCliente.objects.exists())


@override_settings(TENANT_BASE_DOMAIN='localhost')
class ConcurrentAgendaReputationTests(BookingFixture, TransactionTestCase):
    def test_simultaneous_clicks_keep_single_outcome(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from django.test import Client
        self.setup_booking()
        admin = User.objects.create_user('concurrent-rating@example.test', tenant=self.tenant, tipo='ADMIN')
        with patch('whatsapp.services.enviar_confirmacao_agendamento'):
            booking = self.book()
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(admin)
        barrier = Barrier(2)

        def click(client, action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return client.post(reverse('painel:agendamento_' + action, args=[booking.pk]),
                                   HTTP_HOST='marcos.localhost', HTTP_ACCEPT='application/json')
            finally:
                close_old_connections()

        with patch('django.utils.timezone.now', return_value=booking.inicio):
            with ThreadPoolExecutor(max_workers=2) as executor:
                jobs = [executor.submit(click, client, action) for client, action in zip(clients, ['atraso', 'falta'])]
                responses = [job.result(timeout=20) for job in jobs]
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].json()['tipo'], responses[1].json()['tipo'])
        self.assertEqual(ReputacaoCliente.objects.filter(agendamento=booking).count(), 1)
