from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, time
from io import StringIO
from threading import Barrier, Event
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.booking import horarios_disponiveis, registrar_falta
from agenda.models import Agendamento, ReputacaoCliente, ReputacaoClienteAuditoria
from agenda.presentation import timeline_payload
from agenda.test_booking import BookingFixture
from usuarios.models import User
from . import evolution
from .models import Configuracao, Lembrete, RespostaLembrete, RetornoResposta, DEFAULT_MESSAGE
from .reminders import process_reminders, render_message
from .replies import process_reply, parse_messages, process_returns, confirmation_indicator
from .reply_views import webhook_token


class ReplyFixture(BookingFixture):
    def setup_replies(self):
        self.setup_booking()
        self.booking = self.book()
        self.config, _ = Configuracao.objects.update_or_create(tenant=self.tenant, defaults={
            'lembretes_ativos': True, 'confirmar_presenca_whatsapp': True, 'cancelar_whatsapp': True})
        self.now = self.booking.inicio - timedelta(minutes=60)
        self.reminder = self.make_reminder(self.booking, 'sent-1')

    def make_reminder(self, booking, message_id):
        return Lembrete.objects.create(agendamento=booking, status='ENVIADO',
            instancia=evolution.instance(booking.tenant), destinatario=booking.whatsapp_contato,
            mensagem_id=message_id, enviado_em=self.now - timedelta(minutes=1),
            valido_ate=booking.inicio, permite_confirmar=True, permite_cancelar=True)

    def payload(self, option='1', message_id='received-1', quoted='', **changes):
        message = {'conversation': option}
        if quoted:
            message = {'extendedTextMessage': {'text': option, 'contextInfo': {'stanzaId': quoted}}}
        item = {'key': {'id': message_id, 'fromMe': False, 'remoteJid': '5511999991234@s.whatsapp.net'},
                'message': message, 'messageTimestamp': int(self.now.timestamp())}
        item.update(changes)
        return {'event': 'MESSAGES_UPSERT', 'instance': evolution.instance(self.tenant), 'data': item}


@override_settings(DEBUG=True, TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost', 'localhost'],
                   EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class ReminderReplyTests(ReplyFixture, TestCase):
    def setUp(self):
        self.setup_replies()

    def post(self, option='1', message_id='received-1', quoted='', payload=None, token=None, host='marcos.localhost'):
        with patch('whatsapp.replies.timezone.now', return_value=self.now):
            return self.client.post(reverse('whatsapp_appointment_reply'),
                data=payload or self.payload(option, message_id, quoted), content_type='application/json',
                HTTP_HOST=host, HTTP_X_AGENDAMENTO_TOKEN=webhook_token(self.tenant) if token is None else token)

    def test_confirmation_is_not_attendance_and_updates_timeline_and_history(self):
        self.assertEqual(self.post().status_code, 200)
        self.booking.refresh_from_db(); self.reminder.refresh_from_db()
        self.assertEqual(self.booking.status, 'CONFIRMADO')
        self.assertIsNone(self.booking.conclusao_confirmada_em)
        self.assertEqual(self.reminder.presenca_confirmada_em, self.now)
        self.assertFalse(ReputacaoCliente.objects.exists())
        self.assertIn('sua presença está confirmada', RetornoResposta.objects.get().mensagem)
        data = timeline_payload(self.prof, self.day, [self.window])
        self.assertEqual(data['appointments'][0]['whatsappConfirmation'], '🟢 Confirmado pelo cliente')
        admin = User.objects.create_user('reply-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        page = self.client.get(reverse('painel:whatsapp_historico', args=[self.user.whatsapp]), HTTP_HOST='marcos.localhost')
        self.assertContains(page, 'Confirmado pelo cliente')
        self.assertContains(page, 'Presença confirmada em')

    def test_cancellation_releases_slot_and_reuses_reputation(self):
        self.assertEqual(self.post('2').status_code, 200)
        self.booking.refresh_from_db(); self.reminder.refresh_from_db()
        self.assertEqual(self.booking.status, 'CANCELADO')
        self.assertEqual(self.reminder.cancelado_pelo_cliente_em, self.now)
        self.assertEqual(ReputacaoCliente.objects.get().tipo, 'DESMARCOU')
        self.assertIn('09:07', [s['hora'] for s in horarios_disponiveis(self.offer, self.day)])
        self.assertEqual(confirmation_indicator(self.booking), '🔴 Cancelado pelo cliente')
        self.assertEqual(timeline_payload(self.prof, self.day, [self.window])['appointments'], [])
        self.assertIn('cancelado com sucesso', RetornoResposta.objects.get().mensagem)

    def test_late_cancellation_is_audited_without_reputation_change(self):
        self.config.cancelamento_antecedencia_minutos = 90; self.config.save()
        self.post('2')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'CONFIRMADO')
        self.assertFalse(ReputacaoCliente.objects.exists())
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'FORA_DO_PRAZO')
        self.assertNotIn('cancelado com sucesso', RetornoResposta.objects.get().mensagem)

    def test_exact_deadline_is_allowed(self):
        self.config.cancelamento_antecedencia_minutos = 60; self.config.save()
        self.post('2')
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CANCELADO')

    def test_duplicate_webhook_and_distinct_repeated_confirmations(self):
        self.post(); self.post(); self.post(message_id='second-reply')
        self.assertEqual(RespostaLembrete.objects.count(), 2)
        self.assertEqual(RetornoResposta.objects.count(), 1)
        self.assertEqual(RespostaLembrete.objects.get(mensagem_id='second-reply').resultado, 'JA_CONFIRMADO')
        self.assertFalse(ReputacaoCliente.objects.exists())

    def test_duplicate_cancellations_and_confirm_after_cancel_never_reactivate(self):
        self.post('2'); self.post('2'); self.post('2', 'second'); self.post('1', 'third')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'CANCELADO')
        self.assertEqual(ReputacaoCliente.objects.count(), 1)
        self.assertEqual(ReputacaoClienteAuditoria.objects.count(), 0)
        self.assertEqual(RetornoResposta.objects.count(), 1)

    def test_reply_after_start_or_completion_and_old_event_is_ignored(self):
        self.now = self.booking.fim + timedelta(minutes=1)
        self.post('2', quoted='sent-1')
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'EXPIRADO')
        self.assertFalse(ReputacaoCliente.objects.exists())
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CONFIRMADO')

    def test_completed_booking_is_not_changed(self):
        Agendamento.objects.filter(pk=self.booking.pk).update(conclusao_confirmada_em=self.now)
        self.post('2')
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'EXPIRADO')
        self.assertFalse(ReputacaoCliente.objects.exists())

    def test_old_message_cannot_target_new_reminder(self):
        payload = self.payload('2', messageTimestamp=int((self.now - timedelta(hours=2)).timestamp()))
        self.post(payload=payload)
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'SEM_LEMBRETE')
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CONFIRMADO')

    def test_missing_time_and_future_event_cannot_change_booking(self):
        payload = self.payload('2'); del payload['data']['messageTimestamp']
        self.post(payload=payload)
        self.assertFalse(RespostaLembrete.objects.exists())
        self.post(payload=self.payload('2', messageTimestamp=int((self.now + timedelta(hours=1)).timestamp())))
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'DATA_INVALIDA')

    def test_multiple_reminders_require_quoted_identity(self):
        other = self.book(time(9, 47)); self.make_reminder(other, 'sent-2')
        self.post('2')
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'AMBIGUO')
        self.assertFalse(Agendamento.objects.filter(status='CANCELADO').exists())
        self.post('2', 'quoted', quoted='sent-2')
        self.booking.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(self.booking.status, 'CONFIRMADO')
        self.assertEqual(other.status, 'CANCELADO')

    def test_wrong_quote_and_wrong_phone_never_fall_back(self):
        self.post('2', quoted='foreign-message')
        payload = self.payload('2', 'different-phone', quoted='sent-1')
        payload['data']['key']['remoteJid'] = '5511999995678@s.whatsapp.net'
        self.post(payload=payload)
        self.assertFalse(Agendamento.objects.filter(status='CANCELADO').exists())
        self.assertFalse(RetornoResposta.objects.exists())

    def test_rescheduled_booking_invalidates_original_reminder(self):
        Agendamento.objects.filter(pk=self.booking.pk).update(
            inicio=self.booking.inicio + timedelta(minutes=5), fim=self.booking.fim + timedelta(minutes=5))
        self.post('2', quoted='sent-1')
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'EXPIRADO')
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CONFIRMADO')

    def test_invalid_batch_does_not_partially_apply(self):
        payload = self.payload('2')
        payload['data'] = [payload['data'], {'key': 'invalid'}]
        self.assertEqual(self.post(payload=payload).status_code, 400)
        self.assertFalse(RespostaLembrete.objects.exists())

    def test_no_response_has_no_reputation_effect(self):
        with patch('whatsapp.replies.timezone.now', return_value=self.booking.fim + timedelta(minutes=1)):
            self.assertEqual(confirmation_indicator(self.booking), '⚪ Sem resposta')
        self.assertFalse(ReputacaoCliente.objects.exists())

    def test_other_tenant_token_and_instance_are_rejected(self):
        self.assertEqual(self.post(token='bad').status_code, 403)
        self.assertEqual(self.post(token=webhook_token(self.other)).status_code, 403)
        self.assertEqual(self.post(host='wanessa.localhost').status_code, 403)
        payload = self.payload(); payload['instance'] = evolution.instance(self.other)
        self.assertEqual(self.post(payload=payload).status_code, 403)
        self.assertFalse(RespostaLembrete.objects.exists())

    def test_authenticated_other_tenant_cannot_target_foreign_booking(self):
        payload = self.payload('2', quoted='sent-1'); payload['instance'] = evolution.instance(self.other)
        Configuracao.objects.create(tenant=self.other, cancelar_whatsapp=True)
        self.assertEqual(self.post(payload=payload, host='wanessa.localhost', token=webhook_token(self.other)).status_code, 200)
        self.assertEqual(RespostaLembrete.objects.get().tenant_id, self.other.pk)
        self.assertIsNone(RespostaLembrete.objects.get().lembrete_id)
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CONFIRMADO')

    def test_from_me_groups_and_unrelated_events_are_ignored(self):
        for changes in ({'fromMe': True}, {'remoteJid': '123@g.us'}, {'fromMe': None}):
            payload = self.payload('2'); payload['data']['key'].update(changes)
            self.post(payload=payload)
        payload = self.payload('2'); payload['event'] = 'MESSAGES_UPDATE'; self.post(payload=payload)
        self.assertFalse(RespostaLembrete.objects.exists())

    def test_lid_uses_provider_alternative_not_content_number(self):
        payload = self.payload('1'); payload['data']['key'].update(
            remoteJid='opaque@lid', remoteJidAlt='5511999991234@s.whatsapp.net')
        self.post(payload=payload)
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'CONFIRMADO')

    def test_unknown_text_only_guides_a_single_identifiable_reminder(self):
        self.post('3')
        self.assertEqual(RespostaLembrete.objects.get().opcao, 'OUTRO')
        self.assertIn('Digite 1', RetornoResposta.objects.get().mensagem)
        self.assertFalse(ReputacaoCliente.objects.exists())

    def test_independent_settings_and_send_time_permissions(self):
        self.config.confirmar_presenca_whatsapp = False; self.config.save()
        self.post('1'); self.assertEqual(RespostaLembrete.objects.get().resultado, 'DESATIVADO')
        self.post('2', 'cancel'); self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CANCELADO')

    def test_cancellation_disabled_does_not_disable_confirmation(self):
        self.config.cancelar_whatsapp = False; self.config.save()
        self.post('2'); self.post('1', 'confirm')
        self.reminder.refresh_from_db(); self.assertIsNotNone(self.reminder.presenca_confirmada_em)
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CONFIRMADO')

    def test_both_disabled_and_legacy_reminders_do_not_change_booking(self):
        self.config.confirmar_presenca_whatsapp = False; self.config.cancelar_whatsapp = False; self.config.save()
        self.post('2'); self.assertEqual(RespostaLembrete.objects.get().resultado, 'DESATIVADO')
        self.config.confirmar_presenca_whatsapp = True; self.config.save()
        self.reminder.permite_confirmar = False; self.reminder.save()
        self.post('1', 'legacy'); self.assertFalse(RetornoResposta.objects.exists())

    def test_confirmed_customer_can_later_be_marked_as_no_show(self):
        self.post()
        admin = User.objects.create_user('noshowreply@example.test', tenant=self.tenant, tipo='ADMIN')
        with patch('agenda.booking.timezone.now', return_value=self.booking.inicio + timedelta(minutes=1)):
            registrar_falta(tenant=self.tenant, administrador=admin, agendamento_id=self.booking.pk)
        self.reminder.refresh_from_db()
        self.assertIsNotNone(self.reminder.presenca_confirmada_em)
        self.assertEqual(ReputacaoCliente.objects.get().tipo, 'AUSENTE')

    def test_return_failure_does_not_undo_cancel_and_safe_failures_retry(self):
        with patch('whatsapp.evolution.send_text', side_effect=evolution.EvolutionError('Unavailable', retry_safe=True)):
            with self.captureOnCommitCallbacks(execute=True):
                self.post('2')
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CANCELADO')
        delivery = RetornoResposta.objects.get(); self.assertEqual(delivery.status, 'FALHA')
        with patch('whatsapp.evolution.send_text', return_value={'message_id': 'ack'}), \
                patch('whatsapp.replies.timezone.now', return_value=delivery.proxima_tentativa_em):
            self.assertEqual(process_returns(), 1)
            self.assertEqual(process_returns(), 0)

    def test_uncertain_delivery_is_not_blindly_retried(self):
        with patch('whatsapp.evolution.send_text', side_effect=evolution.EvolutionError('timeout')) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.post()
            self.assertEqual(process_returns(), 0)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(RetornoResposta.objects.get().status, 'INCERTO')

    def test_reminder_message_and_delivery_metadata_and_no_duplicates(self):
        self.reminder.delete()
        with patch('whatsapp.reminders.timezone.now', return_value=self.now), \
                patch('whatsapp.evolution.state', return_value='open'), \
                patch('whatsapp.evolution.send_text', return_value={'message_id': 'real-id'}) as send:
            self.assertEqual(process_reminders(), 1)
            self.assertEqual(process_reminders(), 0)
        reminder = Lembrete.objects.get()
        self.assertEqual(reminder.mensagem_id, 'real-id')
        self.assertEqual(reminder.destinatario, self.booking.whatsapp_contato)
        self.assertEqual(reminder.valido_ate, self.booking.inicio)
        self.assertIn('Digite 1 para CONFIRMAR', send.call_args.args[2])
        self.assertIn('Digite 2 para CANCELAR', send.call_args.args[2])

    def test_disabled_interaction_preserves_custom_template(self):
        self.config.confirmar_presenca_whatsapp = False; self.config.cancelar_whatsapp = False
        self.config.mensagem_lembrete = 'Personalizada: {cliente}'
        self.assertEqual(render_message(self.config, self.booking), 'Personalizada: Cliente Teste')
        self.config.cancelar_whatsapp = True
        text = render_message(self.config, self.booking)
        self.assertNotIn('Digite 1', text); self.assertIn('Digite 2', text)

    def test_panel_settings_permissions_and_validation(self):
        admin = User.objects.create_user('settingsreply@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        data = {'acao': 'salvar_respostas', 'cancelar_whatsapp': 'on', 'cancelamento_antecedencia_minutos': 30}
        self.assertEqual(self.client.post(reverse('painel:whatsapp'), data, HTTP_HOST='marcos.localhost').status_code, 302)
        self.config.refresh_from_db()
        self.assertFalse(self.config.confirmar_presenca_whatsapp); self.assertTrue(self.config.cancelar_whatsapp)
        self.assertEqual(self.config.cancelamento_antecedencia_minutos, 30)
        self.assertEqual(self.client.post(reverse('painel:whatsapp'), data, HTTP_HOST='wanessa.localhost').status_code, 403)
        data['cancelamento_antecedencia_minutos'] = -1
        self.assertEqual(self.client.post(reverse('painel:whatsapp'), data, HTTP_HOST='marcos.localhost').status_code, 200)
        self.config.refresh_from_db(); self.assertEqual(self.config.cancelamento_antecedencia_minutos, 30)

    def test_existing_test_inbox_can_process_replies(self):
        from .inbox_views import webhook_token as inbox_token
        with patch('whatsapp.inbox.save_message', return_value=1), patch('whatsapp.replies.timezone.now', return_value=self.now):
            response = self.client.post('/teste/receber/', self.payload(), content_type='application/json',
                HTTP_HOST='marcos.localhost', HTTP_X_TESTZAP_TOKEN=inbox_token(self.tenant))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RespostaLembrete.objects.get().resultado, 'CONFIRMADO')

    def test_webhook_setup_preserves_events_and_refuses_foreign_integration(self):
        with patch('whatsapp.evolution.request', return_value={'url': 'https://other.example/webhook'}):
            with self.assertRaises(CommandError):
                call_command('configurar_webhook_agendamentos', tenant='marcos', aplicar=True, stdout=StringIO())
        target = 'https://marcos.tacombinado.net/whatsapp/respostas/'
        expected = {'enabled': True, 'url': target, 'events': ['CONNECTION_UPDATE', 'MESSAGES_UPSERT'],
                    'headers': {'X-Agendamento-Token': webhook_token(self.tenant)}}
        with patch('whatsapp.evolution.request', side_effect=[{'events': ['CONNECTION_UPDATE']}, {}, expected]) as request:
            call_command('configurar_webhook_agendamentos', tenant='marcos', aplicar=True, stdout=StringIO())
        self.assertEqual(request.call_args_list[1].args[2]['webhook']['events'], expected['events'])


@override_settings(EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class ConcurrentReplyTests(ReplyFixture, TransactionTestCase):
    def test_fast_reply_waits_for_reminder_delivery_metadata(self):
        with patch('whatsapp.services.enviar_confirmacao_agendamento'):
            self.setup_replies()
        self.reminder.delete()
        sending, release, reply_started, reply_done = Event(), Event(), Event(), Event()
        def send(*args):
            sending.set()
            if not release.wait(timeout=10):
                raise RuntimeError('Test did not release delivery')
            return {'message_id': 'sent-new'}
        def reminder_worker():
            close_old_connections()
            try:
                return process_reminders()
            finally:
                close_old_connections()
        def reply_worker():
            close_old_connections()
            try:
                reply_started.set()
                result = process_reply(self.tenant, parse_messages(self.payload('2', quoted='sent-new'))[0])
                reply_done.set()
                return result.resultado
            finally:
                close_old_connections()
        with patch('whatsapp.replies.timezone.now', return_value=self.now), \
                patch('whatsapp.evolution.state', return_value='open'), \
                patch('whatsapp.evolution.send_text', side_effect=send), \
                patch('whatsapp.replies.deliver_return'), ThreadPoolExecutor(max_workers=2) as pool:
            sender = pool.submit(reminder_worker)
            try:
                self.assertTrue(sending.wait(timeout=10))
                reply = pool.submit(reply_worker)
                self.assertTrue(reply_started.wait(timeout=10))
                self.assertFalse(reply_done.wait(timeout=0.2))
            finally:
                release.set()
            self.assertEqual(sender.result(timeout=10), 1)
            self.assertEqual(reply.result(timeout=10), 'CANCELADO')

    def test_concurrent_duplicate_cancellations_apply_once(self):
        self.run_concurrent_cancellations(duplicate=True)

    def test_concurrent_distinct_cancellations_apply_once(self):
        self.run_concurrent_cancellations(duplicate=False)

    def run_concurrent_cancellations(self, duplicate):
        with patch('whatsapp.services.enviar_confirmacao_agendamento'):
            self.setup_replies()
        barrier = Barrier(2)
        def worker(index):
            close_old_connections()
            try:
                incoming = parse_messages(self.payload('2', message_id='same' if duplicate else f'event-{index}'))[0]
                barrier.wait(timeout=10)
                return process_reply(self.tenant, incoming).pk
            finally:
                close_old_connections()
        with patch('whatsapp.replies.deliver_return'), \
                patch('whatsapp.replies.timezone.now', return_value=self.now), \
                ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(worker, range(2)))
        self.assertEqual(ids[0] == ids[1], duplicate)
        self.assertEqual(RespostaLembrete.objects.count(), 1 if duplicate else 2)
        self.assertEqual(RetornoResposta.objects.count(), 1)
        self.assertEqual(ReputacaoCliente.objects.count(), 1)
        self.booking.refresh_from_db(); self.assertEqual(self.booking.status, 'CANCELADO')
