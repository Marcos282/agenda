from datetime import time
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.db import transaction, IntegrityError
from agenda.test_booking import BookingFixture
from agenda.booking import reservar_por_whatsapp, reservar_pelo_painel
from agenda.models import Agendamento
from usuarios.models import User
from .models import Configuracao, Confirmacao, DEFAULT_CONFIRMATION
from .confirmations import send_confirmation
from .evolution import EvolutionError


@override_settings(TENANT_BASE_DOMAIN='localhost')
class ConfirmationTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('confirm-admin@example.test',tenant=self.tenant,tipo='ADMIN')
        self.send = patch('whatsapp.evolution.send_text').start()
        self.addCleanup(patch.stopall)

    def test_post_commit_personalized_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            booking = self.book()
            self.send.assert_not_called()
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.args[1], self.user.whatsapp)
        text = self.send.call_args.args[2]
        for value in ['Cliente Teste','Marcos','Corte','João',self.day.strftime('%d/%m/%Y'),'09:07','Obrigado','horário combinado']:
            self.assertIn(value,text)
        self.assertEqual(Confirmacao.objects.get().status,'ENVIADO')
        self.assertFalse(send_confirmation(tenant_id=self.tenant.pk,agendamento_id=booking.pk))
        self.send.assert_called_once()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Confirmacao.objects.create(agendamento=booking)

    def test_rollback_does_not_send_or_leave_booking(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.book()
                    raise ValueError('rollback')
            except ValueError:
                pass
        self.send.assert_not_called()
        self.assertFalse(Agendamento.objects.exists())
        self.assertFalse(Confirmacao.objects.exists())

    def test_failure_preserves_reservation_and_is_not_retried(self):
        self.send.side_effect = EvolutionError('offline')
        with self.captureOnCommitCallbacks(execute=True):
            booking = self.book()
        booking.refresh_from_db()
        self.assertEqual(booking.status,'CONFIRMADO')
        self.assertEqual(Confirmacao.objects.get().status,'INCERTO')
        send_confirmation(tenant_id=self.tenant.pk,agendamento_id=booking.pk)
        self.send.assert_called_once()

    def test_panel_and_guest_reservations_trigger_confirmation(self):
        for fn in [reservar_por_whatsapp,reservar_pelo_painel]:
            with self.subTest(fn=fn):
                kwargs=dict(tenant=self.tenant,nome='Cliente',whatsapp='(11) 99999-5678',oferta_id=self.offer.pk,
                    dia=self.day,hora=time(9,47),valor_exibido='40.00',duracao_exibida=40)
                if fn==reservar_pelo_painel:
                    kwargs['administrador']=self.admin
                with self.captureOnCommitCallbacks(execute=True):
                    booking=fn(**kwargs)
                self.assertEqual(Confirmacao.objects.get(agendamento=booking).status,'ENVIADO')
                from agenda.booking import cancelar
                cancelar(tenant=self.tenant,cliente=None,agendamento_id=booking.pk)
        self.assertEqual(self.send.call_count,2)

    def test_tenant_setting_disabled_and_snapshot_number(self):
        Configuracao.objects.create(tenant=self.other,confirmacoes_ativas=False)
        config=Configuracao.objects.create(tenant=self.tenant,confirmacoes_ativas=False)
        with self.captureOnCommitCallbacks(execute=True):
            booking=self.book()
        self.send.assert_not_called()
        config.confirmacoes_ativas=True
        config.mensagem_confirmacao='Obrigado, {cliente}! {estabelecimento} espera você em {data} às {hora}.'
        config.save()
        old=self.user.whatsapp
        self.user.whatsapp='+5521999991234'
        self.user.save()
        send_confirmation(tenant_id=self.tenant.pk,agendamento_id=booking.pk)
        self.assertEqual(self.send.call_args.args[1],old)
        with self.assertRaises(Agendamento.DoesNotExist):
            send_confirmation(tenant_id=self.other.pk,agendamento_id=booking.pk)

    @patch('whatsapp.evolution.configured',return_value=False)
    def test_panel_variables_save_and_history(self, configured):
        self.client.force_login(self.admin)
        url=reverse('painel:whatsapp')
        response=self.client.get(url,HTTP_HOST='marcos.localhost')
        self.assertContains(response,'Boas-vindas e agradecimento')
        self.assertContains(response,'{cliente}')
        data=dict(acao='salvar_confirmacao',confirmacoes_ativas='on',mensagem_confirmacao='Obrigado {cliente}, até {hora}!',
            antecedencia_minutos=120,mensagem_lembrete='Lembrete {cliente}')
        self.assertEqual(self.client.post(url,data,HTTP_HOST='marcos.localhost').status_code,302)
        with self.captureOnCommitCallbacks(execute=True):
            self.book()
        self.assertEqual(Confirmacao.objects.get().status,'ENVIADO')
        data['mensagem_confirmacao']='{variavel_invalida}'
        response=self.client.post(url,data,HTTP_HOST='marcos.localhost')
        self.assertTrue(response.context['confirmacao_form'].errors)
