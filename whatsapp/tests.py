from datetime import timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.booking import cancelar, reservar_pelo_painel
from usuarios.models import User
from .models import Configuracao, Lembrete, DEFAULT_MESSAGE
from .reminders import process_reminders
from .views import ConfiguracaoForm
from . import evolution


class WhatsAppTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('waadmin@example.test', 'Test!2026password', tenant=self.tenant, tipo='ADMIN')
        self.config = Configuracao.objects.create(tenant=self.tenant, lembretes_ativos=True)
        self.booking = self.book()

    def process(self, minutes=120):
        with patch('whatsapp.reminders.timezone.now', return_value=self.booking.inicio-timedelta(minutes=minutes)), patch('whatsapp.evolution.state', return_value='open'):
            return process_reminders()

    @patch('whatsapp.evolution.send_text')
    def test_due_once_with_local_time(self, send):
        self.assertEqual(self.process(121), 0)
        self.assertEqual(self.process(), 1)
        self.assertEqual(self.process(119), 0)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], '+5511999991234')
        self.assertIn('09:07', send.call_args.args[2])
        self.assertEqual(Lembrete.objects.get().status, 'ENVIADO')

    @patch('whatsapp.evolution.send_text')
    def test_adjustable_disabled_and_past(self, send):
        self.config.antecedencia_minutos = 60
        self.config.save()
        self.assertEqual(self.process(120), 0)
        self.config.lembretes_ativos = False
        self.config.save()
        self.assertEqual(self.process(30), 0)
        self.config.lembretes_ativos = True
        self.config.save()
        self.assertEqual(self.process(0), 0)
        self.assertEqual(self.process(30), 1)

    @patch('whatsapp.evolution.send_text')
    def test_cancelled_never_sent(self, send):
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=self.booking.pk)
        self.assertEqual(self.process(), 0)
        send.assert_not_called()

    @patch('whatsapp.evolution.send_text', side_effect=evolution.EvolutionError('timeout'))
    def test_uncertain_not_retried(self, send):
        self.assertEqual(self.process(), 0)
        self.assertEqual(self.process(), 0)
        send.assert_called_once()
        self.assertEqual(Lembrete.objects.get().status, 'INCERTO')

    @patch('whatsapp.evolution.send_text')
    def test_guest_contact(self, send):
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=self.booking.pk)
        self.booking = reservar_pelo_painel(tenant=self.tenant, administrador=self.admin,
            nome='Balcão', whatsapp='21999995678', oferta_id=self.offer.pk, dia=self.day,
            hora=self.booking.inicio.astimezone(ZoneInfo(self.tenant.timezone)).time(),
            valor_exibido='40.00', duracao_exibida=40)
        self.assertEqual(self.process(), 1)
        self.assertEqual(send.call_args.args[1], '+5521999995678')

    def test_form_validation(self):
        for template in ['{cliente.__class__}', '{unknown}', '{cliente!r}', '{', '{cliente:>99}']:
            form = ConfiguracaoForm({'antecedencia_minutos':120, 'mensagem_lembrete':template})
            self.assertFalse(form.is_valid())
        for minutes in [0, 10081]:
            self.assertFalse(ConfiguracaoForm({'antecedencia_minutos':minutes, 'mensagem_lembrete':DEFAULT_MESSAGE}).is_valid())

    @patch('whatsapp.evolution.connection_info', return_value={'state':'missing','number':''})
    def test_panel_permissions_and_tenant_scope(self, info):
        url = reverse('painel:whatsapp')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url, HTTP_HOST='marcos.localhost').status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'WhatsApp')
        self.assertContains(response, '120')
        self.assertEqual(self.client.get(url, HTTP_HOST='wanessa.localhost').status_code, 403)
        self.client.post(url, {'acao':'salvar', 'lembretes_ativos':'on', 'antecedencia_minutos':60, 'mensagem_lembrete':'Olá {cliente}'}, HTTP_HOST='marcos.localhost')
        self.config.refresh_from_db()
        self.assertEqual(self.config.antecedencia_minutos, 60)
        self.assertFalse(Configuracao.objects.filter(tenant=self.other).exists())

    @override_settings(EVOLUTION_INSTANCE_PREFIX='barbe_test')
    @patch('whatsapp.evolution.request')
    def test_adapter_scope_and_payload(self, request):
        request.return_value = [{'name':f'barbe_test_{self.other.pk}', 'connectionStatus':'open'}]
        self.assertEqual(evolution.state(self.tenant), 'missing')
        request.return_value = {'key':{'id':'test'}}
        evolution.send_text(self.tenant, '+5511999991234', 'Olá')
        request.assert_called_with('POST', f'/message/sendText/barbe_test_{self.tenant.pk}', {'number':'5511999991234', 'text':'Olá'})

    @patch('whatsapp.evolution.send_text')
    def test_disconnected_leaves_pending(self, send):
        with patch('whatsapp.evolution.state', return_value='close'):
            self.assertEqual(process_reminders(), 0)
        self.assertFalse(Lembrete.objects.exists())
        send.assert_not_called()

    @patch('whatsapp.evolution.send_text')
    def test_persisted_claim_never_repeated(self, send):
        Lembrete.objects.create(agendamento=self.booking)
        self.assertEqual(self.process(), 0)
        send.assert_not_called()


    @override_settings(EVOLUTION_API_URL='http://example.test', EVOLUTION_API_KEY='test')
    @patch('whatsapp.evolution.connection_info')
    def test_panel_connection_status_and_number(self, info):
        self.client.force_login(self.admin)
        url = reverse('painel:whatsapp')
        for state, number, label in [('open', '+5511999991234', 'Conectado'), ('close', '', 'Desconectado'), ('connecting', '', 'Conectando')]:
            info.return_value = {'state':state, 'number':number}
            response = self.client.get(url, HTTP_HOST='marcos.localhost')
            self.assertContains(response, label)
            if number:
                self.assertContains(response, number)
            else:
                self.assertNotContains(response, '+5511999991234')
        info.side_effect = evolution.EvolutionError('offline')
        response = self.client.get(url, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'Status indisponível')
        self.assertNotContains(response, 'Nenhum número conectado.')

    @patch('whatsapp.evolution.request')
    def test_connection_number_is_scoped_and_not_stale(self, request):
        request.return_value = [
            {'name':evolution.instance(self.other), 'connectionStatus':'open', 'ownerJid':'5521999995678@s.whatsapp.net'},
            {'name':evolution.instance(self.tenant), 'connectionStatus':'open', 'ownerJid':'5511999991234:2@s.whatsapp.net'},
        ]
        self.assertEqual(evolution.connection_info(self.tenant), {'state':'open', 'number':'+5511999991234'})
        request.return_value[1]['connectionStatus'] = 'close'
        self.assertEqual(evolution.connection_info(self.tenant)['number'], '')


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import TransactionTestCase


class ConcurrentReminderTests(BookingFixture, TransactionTestCase):
    def test_two_workers_send_once(self):
        self.setup_booking()
        booking = self.book()
        Configuracao.objects.create(tenant=self.tenant, lembretes_ativos=True)
        barrier = Barrier(2)

        def connected(tenant):
            barrier.wait(timeout=10)
            return 'open'

        def worker():
            close_old_connections()
            try:
                return process_reminders()
            finally:
                close_old_connections()

        with patch('whatsapp.reminders.timezone.now', return_value=booking.inicio-timedelta(minutes=120)), patch('whatsapp.evolution.state', side_effect=connected), patch('whatsapp.evolution.send_text') as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(sum(results), 1)
        send.assert_called_once()
        self.assertEqual(Lembrete.objects.count(), 1)
