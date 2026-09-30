from concurrent.futures import ThreadPoolExecutor
from datetime import time
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from usuarios.models import ContatoCliente, User
from .booking import reservar_por_whatsapp
from .models import Agendamento
from .test_booking import BookingFixture


class GuestBookingTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.host = {'HTTP_HOST': 'marcos.localhost'}

    def test_guest_books_tracks_and_cancels_without_account(self):
        accounts = User.objects.count()
        page = self.client.get(self.slots_url(), **self.host)
        self.assertContains(page, 'name="nome"')
        self.assertContains(page, 'name="whatsapp"')
        self.assertNotContains(page, 'name="password"')
        self.assertNotContains(page, 'name="email"')
        self.assertNotContains(page, 'href="/cadastro/"')
        response = self.client.post(self.slots_url(), self.payload(cliente_id=self.foreign.pk, tenant_id=self.other.pk), **self.host)
        booking = Agendamento.objects.get()
        self.assertEqual(response.url, reverse('agenda:acompanhar', args=[booking.acesso_token]))
        self.assertIsNone(booking.cliente_id)
        self.assertEqual(booking.contato.tenant_id, self.tenant.pk)
        self.assertEqual(booking.whatsapp_contato, '+5511999991234')
        self.assertEqual(User.objects.count(), accounts)
        page = self.client.get(response.url, **self.host)
        self.assertContains(page, 'Confirmado')
        self.assertContains(page, response.url)
        self.assertIn('no-store', page['Cache-Control'])
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        self.assertEqual(self.client.get(reverse('agenda:meus'), **self.host).context['agendamentos'].paginator.count, 1)
        other_device = Client()
        self.assertContains(other_device.get(response.url, **self.host), 'Confirmado')
        self.assertEqual(other_device.post(response.url, **self.host).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CANCELADO')
        self.assertContains(self.client.get(response.url, **self.host), 'Cancelado')

    def test_phone_reused_but_prior_bookings_and_accounts_not_exposed(self):
        account_booking = self.book(time(13,11))
        self.client.post(self.slots_url(), self.payload(nome='Primeiro Nome'), **self.host)
        first = Agendamento.objects.get(cliente__isnull=True)
        visitor = Client()
        response = visitor.post(self.slots_url(), self.payload(nome='Outro Nome', hora='09:47', whatsapp='+5511999991234'), **self.host)
        self.assertEqual(response.status_code, 302)
        second = Agendamento.objects.exclude(pk__in=[first.pk, account_booking.pk]).get()
        self.assertEqual(first.contato_id, second.contato_id)
        self.assertEqual(ContatoCliente.objects.count(), 1)
        self.assertEqual(second.cliente_nome, 'Outro Nome')
        self.assertEqual(second.contato.nome, 'Primeiro Nome')
        self.assertEqual(visitor.get(reverse('agenda:meus'), **self.host).context['agendamentos'].paginator.count, 1)
        for booking in [first, account_booking]:
            url = reverse('agenda:detalhe', args=[booking.pk])
            self.assertEqual(visitor.get(url, **self.host).status_code, 404)
            self.assertEqual(visitor.post(url, **self.host).status_code, 404)
        self.assertEqual(visitor.get(reverse('agenda:acompanhar', args=[uuid4()]), **self.host).status_code, 404)
        self.assertEqual(visitor.get(response.url, HTTP_HOST='wanessa.localhost').status_code, 404)

    def test_invalid_input_conflict_quote_and_csrf(self):
        for changes in [{'nome':' '}, {'whatsapp':''}, {'whatsapp':'123'}, {'cotacao':'invalid'}]:
            self.assertEqual(self.client.post(self.slots_url(), self.payload(**changes), **self.host).status_code, 400)
        self.assertFalse(ContatoCliente.objects.exists())
        self.book()
        self.assertEqual(self.client.post(self.slots_url(), self.payload(), **self.host).status_code, 409)
        self.assertFalse(ContatoCliente.objects.exists())
        secure = Client(enforce_csrf_checks=True)
        self.assertEqual(secure.post(self.slots_url(), self.payload(hora='09:47'), **self.host).status_code, 403)
        response = self.client.post(self.slots_url(), self.payload(hora='09:47'), **self.host)
        self.assertEqual(secure.post(response.url, **self.host).status_code, 403)

    def test_inactive_contact_rejected_and_tenant_scoped(self):
        foreign = ContatoCliente.objects.create(tenant=self.other, nome='Outro', whatsapp='11999991234')
        self.client.post(self.slots_url(), self.payload(), **self.host)
        booking = Agendamento.objects.get()
        self.assertNotEqual(booking.contato_id, foreign.pk)
        booking.contato.is_active = False
        booking.contato.save()
        self.assertEqual(self.client.post(self.slots_url(), self.payload(hora='09:47'), **self.host).status_code, 409)


class ConcurrentGuestTests(BookingFixture, TransactionTestCase):
    def test_same_phone_concurrently_reuses_contact(self):
        self.setup_booking()
        barrier = Barrier(2)

        def reserve(hour):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reservar_por_whatsapp(tenant=self.tenant, nome='Cliente', whatsapp='11999991234',
                    acesso_publico=True, oferta_id=self.offer.pk, dia=self.day, hora=hour,
                    valor_exibido='40.00', duracao_exibida=40).contato_id
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            contacts = list(pool.map(reserve, [time(9,7), time(9,47)]))
        self.assertEqual(contacts[0], contacts[1])
        self.assertEqual(ContatoCliente.objects.count(), 1)
        self.assertEqual(Agendamento.objects.filter(acesso_token__isnull=False).count(), 2)
