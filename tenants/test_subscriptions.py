from datetime import datetime, date, time, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.models import Agendamento
from tenants.models import Tenant
from tenants.subscriptions import subscription_status
from usuarios.models import User
from whatsapp.models import AvisoAssinatura
from whatsapp.subscriptions import enviar_aviso_assinatura


@override_settings(TENANT_BASE_DOMAIN='localhost', DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='',
                   ALLOWED_HOSTS=['.localhost'], EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class SubscriptionTests(BookingFixture, TestCase):
    def setUp(self):
        self.clock = patch('django.utils.timezone.now', return_value=datetime(2026, 12, 1, 15, tzinfo=dt_timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.setup_booking()
        self.admin = User.objects.create_user('owner@test.com', tenant=self.tenant, tipo='ADMIN')
        self.host = {'HTTP_HOST': 'marcos.localhost'}

    def expire(self, day=date(2026, 11, 27)):
        Tenant.objects.filter(pk=self.tenant.pk).update(expira_em=day)
        self.tenant.refresh_from_db()

    def test_new_registration_sixty_days_and_existing_dates_untouched(self):
        self.assertEqual(self.tenant.data_expiracao, date(2027, 1, 30))
        self.expire(date(2026, 12, 15))
        self.tenant.nome = 'Novo nome'
        self.tenant.save()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.data_expiracao, date(2026, 12, 15))

    def test_initial_free_and_following_thirty_days_are_regular(self):
        for day in (1, 29, 30, 31, 51):
            state = subscription_status(self.tenant, now=datetime(2026, 12, 1, 15, tzinfo=dt_timezone.utc) + timedelta(days=day))
            self.assertFalse(state.bloqueado)
            self.assertEqual(state.cor, 'verde')

    def test_calendar_boundaries_colors_and_full_grace_days(self):
        self.expire(date(2026, 12, 31))
        for instant, cor in (
            ('2026-12-23T15:00:00Z', 'verde'), ('2026-12-24T15:00:00Z', 'azul'),
            ('2026-12-28T15:00:00Z', 'amarelo'), ('2027-01-01T02:59:59Z', 'amarelo'),
            ('2027-01-01T03:00:00Z', 'laranja'), ('2027-01-04T02:59:59Z', 'laranja'),
            ('2027-01-04T03:00:00Z', 'vermelho')):
            with self.subTest(instant=instant):
                state = subscription_status(self.tenant, now=datetime.fromisoformat(instant))
                self.assertEqual(state.cor, cor)
                self.assertEqual(state.bloqueado, cor == 'vermelho')

    def test_grace_allows_booking_and_other_tenant_is_independent(self):
        self.expire(date(2026, 11, 28))
        self.assertIsNotNone(self.book())
        self.expire()
        self.assertTrue(self.tenant.agendamentos_bloqueados)
        self.assertFalse(self.other.agendamentos_bloqueados)

    def test_blocked_service_rejects_stale_tenant_and_preserves_existing(self):
        booking = self.book()
        Tenant.objects.filter(pk=self.tenant.pk).update(expira_em=date(2026, 11, 27))
        with self.assertRaisesMessage(ValidationError, 'temporariamente indisponíveis'):
            self.book(hora=time(10, 7))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CONFIRMADO')
        booking.cliente_nome = 'Atualização permitida'
        booking.save()
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_public_site_and_catalog_remain_visible_direct_get_and_post_blocked(self):
        self.expire()
        for url in (reverse('home'), reverse('loja'), reverse('loja_item', args=[self.offer.pk])):
            page = self.client.get(url, follow=True, **self.host)
            self.assertContains(page, 'Marcos')
            self.assertNotContains(page, 'assinatura venceu')
        page = self.client.get(reverse('loja_item', args=[self.offer.pk]), follow=True, **self.host)
        self.assertContains(page, 'Agendamentos temporariamente indisponíveis')
        self.assertContains(page, 'Corte')
        for method in (self.client.get, self.client.post):
            page = method(self.slots_url(), **self.host)
            self.assertEqual(page.status_code, 503)
        self.assertFalse(Agendamento.objects.exists())

    def test_owner_panel_read_access_and_new_booking_blocked(self):
        self.expire()
        self.client.force_login(self.admin)
        for name in ('inicio', 'agenda', 'clientes', 'profissionais', 'servicos', 'mensalidade'):
            page = self.client.get(reverse('painel:' + name), **self.host)
            self.assertContains(page, 'Reativar assinatura')
            self.assertContains(page, 'renewal-vermelho')
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(reverse('painel:agendamento_novo'), **self.host).status_code, 503)

    def test_warning_ranges_use_actual_remaining_days(self):
        self.client.force_login(self.admin)
        for days, color, text in ((7, 'azul', 'vence em 7 dias'), (3, 'amarelo', 'Faltam 3 dias'),
                                  (-1, 'laranja', 'Tempo restante'), (-4, 'vermelho', 'Reativar assinatura')):
            self.expire(date(2026, 12, 1) + timedelta(days=days))
            page = self.client.get(reverse('painel:inicio'), **self.host)
            self.assertContains(page, text)
            self.assertContains(page, 'renewal-' + color)
            self.assertContains(page, 'aria-label="Situação da assinatura"', count=1)

    @override_settings(EVOLUTION_API_URL='https://example.invalid', EVOLUTION_API_KEY='test')
    @patch('whatsapp.subscriptions.get_provider')
    def test_owner_notices_deduplicated_per_expiry_and_milestone(self, provider):
        self.tenant.telefone = '11999991234'
        self.tenant.save()
        for days in (3, 0, -4):
            self.expire(date(2026, 12, 1) + timedelta(days=days))
            self.assertTrue(enviar_aviso_assinatura(self.tenant.pk))
            self.assertFalse(enviar_aviso_assinatura(self.tenant.pk))
        self.assertEqual(provider.return_value.send_text.call_count, 3)
        self.assertEqual(AvisoAssinatura.objects.count(), 3)

    def test_direct_model_creation_rejected_but_existing_history_is_readable(self):
        original = self.book()
        self.expire()
        copy = Agendamento.objects.get(pk=original.pk)
        copy.pk = None
        copy._state.adding = True
        copy.inicio += timedelta(hours=2)
        copy.fim += timedelta(hours=2)
        with self.assertRaisesMessage(ValidationError, 'temporariamente indisponíveis'):
            copy.save()
        self.assertTrue(Agendamento.objects.filter(pk=original.pk).exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('agenda:meus'), **self.host).status_code, 200)

    @override_settings(EVOLUTION_API_URL='https://example.invalid', EVOLUTION_API_KEY='test')
    @patch('whatsapp.subscriptions.get_provider')
    def test_uncertain_notice_is_not_repeated(self, provider):
        self.tenant.telefone = '11999991234'
        self.tenant.save()
        self.expire()
        provider.return_value.send_text.side_effect = TimeoutError
        self.assertFalse(enviar_aviso_assinatura(self.tenant.pk))
        self.assertFalse(enviar_aviso_assinatura(self.tenant.pk))
        self.assertEqual(provider.return_value.send_text.call_count, 1)
        self.assertEqual(AvisoAssinatura.objects.get().status, 'INCERTO')
