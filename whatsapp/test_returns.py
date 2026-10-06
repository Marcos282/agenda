from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento, ReputacaoCliente
from catalogo.models import ProfissionalServico, Servico
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import ContatoCliente, User, WhatsAppBloqueado
from .models import Configuracao, LembreteRetorno
from .returns import processar_retornos, renderizar_mensagem_retorno
from .views import RetornoForm


class ReturnFixture:
    def setup_returns(self):
        self.tenant = Tenant.objects.create(nome='Tá Combinado', subdomain='marcos', timezone='America/Araguaina', plano=Tenant.Plano.ILIMITADO)
        self.other = Tenant.objects.create(nome='Outra loja', subdomain='outra')
        self.contact = ContatoCliente.objects.create(tenant=self.tenant, nome='Marcos', whatsapp='11999991234')
        self.prof = Profissional.objects.create(tenant=self.tenant, nome='João')
        self.service = Servico.objects.create(tenant=self.tenant, nome='Corte')
        self.offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=self.prof,
            servico=self.service, valor='40.00', duracao_minutos=40)
        self.config = Configuracao.objects.create(tenant=self.tenant, retornos_ativos=True)
        self.now = datetime(2026, 11, 5, 8, tzinfo=ZoneInfo(self.tenant.timezone))
        for tenant in [self.tenant, self.other]:
            tenant.expira_em = self.now.date() + timedelta(days=90)
            tenant.save(update_fields=['expira_em'])
        self.send = patch('whatsapp.returns.get_provider').start().return_value.send_text
        self.send.return_value = {'message_id': 'return-message-id', 'provider': 'evolution'}
        self.addCleanup(patch.stopall)

    def attendance(self, days=30, *, contact=None, tipo='CONCLUIDO', tenant=None,
                   offer=None, status='CONFIRMADO', hour=10, rated=True, confirmed=True):
        tenant, offer = tenant or self.tenant, offer or self.offer
        contact = contact or self.contact
        start = (self.now - timedelta(days=days)).replace(hour=hour)
        booking = Agendamento.objects.create(tenant=tenant, contato=contact, oferta=offer,
            profissional=offer.profissional, cliente_nome=contact.nome, cliente_whatsapp=contact.whatsapp,
            servico_nome=offer.servico.nome, profissional_nome=offer.profissional.nome,
            inicio=start, fim=start + timedelta(minutes=40), valor='40.00', duracao_minutos=40,
            status=status, cancelado_em=start if status == 'CANCELADO' else None,
            conclusao_confirmada_em=start + timedelta(minutes=40) if confirmed else None,
            nao_compareceu_em=start if status == 'NAO_COMPARECEU' else None)
        if rated:
            ReputacaoCliente.objects.create(tenant=tenant, agendamento=booking,
                whatsapp_normalizado=contact.whatsapp, tipo=tipo,
                pontuacao={'CONCLUIDO': 4, 'ATRASADO': 3, 'DESMARCOU': 2, 'AUSENTE': 1}[tipo])
        return booking


@override_settings(TENANT_BASE_DOMAIN='localhost')
class ReturnTests(ReturnFixture, TestCase):
    def setUp(self):
        self.setup_returns()

    def test_calendar_30_days_and_single_send_on_later_runs(self):
        booking = self.attendance()
        self.assertEqual(processar_retornos(self.now - timedelta(days=1))['enviados'], 0)
        self.assertEqual(processar_retornos(self.now)['enviados'], 1)
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.assertEqual(processar_retornos(self.now + timedelta(days=5))['enviados'], 0)
        self.send.assert_called_once()
        claim = LembreteRetorno.objects.get(agendamento=booking)
        self.assertEqual(claim.status, 'ENVIADO')
        self.assertIsNotNone(claim.enviado_em)
        self.assertEqual(claim.destinatario, self.contact.whatsapp)
        self.assertEqual(claim.resposta_api, {'message_id': 'return-message-id'})
        with self.assertRaises(IntegrityError), transaction.atomic():
            LembreteRetorno.objects.create(agendamento=booking)

    def test_latest_visit_resets_cycle_across_names_and_customer_accounts(self):
        self.attendance(days=60)
        renamed = ContatoCliente.objects.create(tenant=self.tenant, nome='Outro nome', whatsapp=self.contact.whatsapp)
        professional = Profissional.objects.create(tenant=self.tenant, nome='Outra profissional')
        service = Servico.objects.create(tenant=self.tenant, nome='Barba')
        offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=professional,
            servico=service, valor='40.00', duracao_minutos=40)
        recent = self.attendance(days=5, contact=renamed, offer=offer)
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.assertEqual(processar_retornos(self.now + timedelta(days=25))['enviados'], 1)
        self.assertEqual(LembreteRetorno.objects.get().agendamento_id, recent.pk)

    def test_new_visit_after_success_starts_another_cycle(self):
        self.attendance()
        processar_retornos(self.now)
        # Example: Nov 12 visit after Nov 5 reminder, Dec 12 reminder.
        self.now = datetime(2026, 12, 12, 8, tzinfo=ZoneInfo(self.tenant.timezone))
        second = self.attendance(days=30)
        self.assertEqual(processar_retornos(self.now - timedelta(days=1))['enviados'], 0)
        self.assertEqual(processar_retornos(self.now)['enviados'], 1)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(LembreteRetorno.objects.filter(status='ENVIADO').count(), 2)
        self.assertTrue(LembreteRetorno.objects.filter(agendamento=second).exists())

    def test_user_and_contact_share_cycle_and_snapshot_survives_number_change(self):
        self.attendance(days=60)
        booking = self.attendance(days=5)
        user = User.objects.create_user('return-user@example.test', tenant=self.tenant,
            whatsapp=self.contact.whatsapp)
        booking.contato = None
        booking.cliente = user
        booking.save(update_fields=['contato', 'cliente'])
        user.whatsapp = '+5511999995678'
        user.save()
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.assertEqual(processar_retornos(self.now + timedelta(days=25))['enviados'], 1)
        self.assertEqual(self.send.call_args.args[1], self.contact.whatsapp)

    def test_cutoff_uses_tenant_local_day_not_utc_day(self):
        booking = self.attendance()
        # Oct 6 23:30 local ends on Oct 7 in UTC; it is due Nov 5 locally.
        booking.inicio = datetime(2026, 10, 6, 23, 30, tzinfo=ZoneInfo(self.tenant.timezone))
        booking.fim = booking.inicio + timedelta(minutes=40)
        booking.save(update_fields=['inicio', 'fim'])
        # The visit actually ends Oct 7 locally, so Nov 5 is too early.
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.assertEqual(processar_retornos(self.now + timedelta(days=1))['enviados'], 1)

    def test_checkbox_disabled_between_claim_and_send_prevents_delivery(self):
        self.attendance()
        manager = LembreteRetorno.objects
        original = manager.get_or_create

        def disable_after_claim(*args, **kwargs):
            result = original(*args, **kwargs)
            Configuracao.objects.filter(pk=self.config.pk).update(retornos_ativos=False)
            return result

        with patch.object(manager, 'get_or_create', side_effect=disable_after_claim):
            self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.send.assert_not_called()
        self.assertEqual(LembreteRetorno.objects.get().status, 'IGNORADO')

    def test_completed_outcomes_only_not_registration_or_elapsed_booking(self):
        self.attendance(days=31, rated=False)
        self.attendance(days=35, confirmed=False)
        self.attendance(days=32, status='CANCELADO', tipo='DESMARCOU')
        self.attendance(days=33, status='NAO_COMPARECEU', tipo='AUSENTE')
        self.attendance(days=-1, tipo='ATRASADO')
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        late = self.attendance(days=34, tipo='ATRASADO')
        self.assertEqual(processar_retornos(self.now)['enviados'], 1)
        self.assertEqual(LembreteRetorno.objects.get().agendamento_id, late.pk)

    def test_disabled_tenant_and_inactive_or_blocked_customer(self):
        self.attendance()
        self.config.retornos_ativos = False
        self.config.save()
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.config.retornos_ativos = True
        self.config.save()
        self.tenant.ativo = False
        self.tenant.save()
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.tenant.ativo = True
        self.tenant.save()
        self.contact.is_active = False
        self.contact.save()
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.contact.is_active = True
        self.contact.save()
        WhatsAppBloqueado.objects.create(tenant=self.tenant, whatsapp=self.contact.whatsapp)
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.send.assert_not_called()

    def test_transport_error_or_unconfirmed_response_is_audited_not_resent(self):
        self.attendance()
        self.send.side_effect = TimeoutError('secret provider detail')
        self.assertEqual(processar_retornos(self.now)['incertos'], 1)
        claim = LembreteRetorno.objects.get()
        self.assertEqual(claim.status, 'INCERTO')
        self.assertIsNone(claim.enviado_em)
        self.assertNotIn('secret', claim.erro)
        self.assertTrue(claim.mensagem)
        self.send.side_effect = None
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.send.assert_called_once()

    def test_provider_must_confirm_acceptance_and_abandoned_claim_is_not_resent(self):
        first = self.attendance()
        self.send.return_value = {}
        self.assertEqual(processar_retornos(self.now)['incertos'], 1)
        self.assertIsNone(LembreteRetorno.objects.get().enviado_em)
        second_contact = ContatoCliente.objects.create(tenant=self.tenant, nome='Ana', whatsapp='11999995678')
        second = self.attendance(contact=second_contact, hour=12)
        LembreteRetorno.objects.create(agendamento=second, destinatario=second_contact.whatsapp)
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(LembreteRetorno.objects.get(agendamento=first).status, 'INCERTO')

    def test_safe_preflight_failure_can_retry_after_template_correction(self):
        self.attendance()
        self.config.mensagem_retorno = '{unknown}'
        self.config.save()
        self.assertEqual(processar_retornos(self.now)['erros'], 1)
        claim = LembreteRetorno.objects.get()
        self.assertEqual(claim.status, 'ERRO')
        self.assertIsNone(claim.enviado_em)
        self.send.assert_not_called()
        self.config.mensagem_retorno = 'Olá, {nome}! {estabelecimento}'
        self.config.save()
        self.assertEqual(processar_retornos(self.now)['enviados'], 1)
        self.assertEqual(LembreteRetorno.objects.count(), 1)

    def test_missing_values_safe_variables_and_cross_tenant_render_rejected(self):
        booking = self.attendance()
        booking.cliente_nome = ''
        booking.profissional_nome = ''
        text = renderizar_mensagem_retorno(self.tenant, booking,
            '{nome} / {estabelecimento} / {profissional} / {ultimo_atendimento}')
        self.assertEqual(text, 'cliente / Tá Combinado / nossa equipe / 06/10/2026')
        with self.assertRaises(ValidationError):
            renderizar_mensagem_retorno(self.other, booking, '{nome}')
        for template in ['{nome.__class__}', '{nome!r}', '{nome:>20}', '{cliente}', '{']:
            form = RetornoForm(data={'retornos_ativos': True, 'mensagem_retorno': template}, instance=self.config)
            self.assertFalse(form.is_valid(), template)

    def test_tenant_isolation_same_number_independent_cycle(self):
        own = self.attendance()
        other_contact = ContatoCliente.objects.create(tenant=self.other, nome='Cliente da outra loja',
            whatsapp=self.contact.whatsapp)
        other_prof = Profissional.objects.create(tenant=self.other, nome='Maria')
        other_service = Servico.objects.create(tenant=self.other, nome='Outro corte')
        other_offer = ProfissionalServico.objects.create(tenant=self.other, profissional=other_prof,
            servico=other_service, valor='40.00', duracao_minutos=40)
        foreign = self.attendance(tenant=self.other, contact=other_contact, offer=other_offer, days=10)
        Configuracao.objects.create(tenant=self.other, retornos_ativos=True)
        self.assertEqual(processar_retornos(self.now)['enviados'], 1)
        self.assertEqual(self.send.call_args.args[0].pk, self.tenant.pk)
        self.assertEqual(LembreteRetorno.objects.get().agendamento_id, own.pk)
        self.assertFalse(LembreteRetorno.objects.filter(agendamento=foreign).exists())

    @patch('whatsapp.evolution.configured', return_value=False)
    def test_panel_configuration_is_tenant_scoped_and_audit_is_visible(self, configured):
        booking = self.attendance()
        processar_retornos(self.now)
        admin = User.objects.create_user('return-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        other_config = Configuracao.objects.create(tenant=self.other)
        url = reverse('painel:whatsapp')
        response = self.client.get(url, HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'Enviar lembrete de retorno após 30 dias')
        self.assertContains(response, 'Atendimento #'+str(booking.pk))
        response = self.client.post(url, {'acao': 'salvar_retorno', 'retornos_ativos': 'on',
            'mensagem_retorno': 'Olá, {nome}! {ultimo_atendimento}', 'tenant': self.other.pk},
            HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        other_config.refresh_from_db()
        self.assertTrue(self.config.retornos_ativos)
        self.assertFalse(other_config.retornos_ativos)
        self.assertEqual(self.config.mensagem_retorno, 'Olá, {nome}! {ultimo_atendimento}')
        self.assertEqual(self.client.get(url, HTTP_HOST='outra.localhost').status_code, 403)
        response = self.client.post(url, {'acao': 'salvar_retorno', 'mensagem_retorno': '{nome}'},
            HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertFalse(self.config.retornos_ativos)

    def test_command_runs_without_opening_panel(self):
        self.attendance()
        output = StringIO()
        with patch('whatsapp.returns.timezone.now', return_value=self.now):
            call_command('enviar_lembretes_30_dias', stdout=output)
        self.assertIn('enviados=1', output.getvalue())
        self.send.assert_called_once()

    def test_explicit_confirmation_enables_cycle_idempotently_and_preserves_late_outcome(self):
        from agenda.reputation import confirmar_conclusao
        admin = User.objects.create_user('completion-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        booking = self.attendance(confirmed=False, tipo='ATRASADO')
        self.assertEqual(processar_retornos(self.now)['enviados'], 0)
        with patch('agenda.reputation.timezone.now', return_value=self.now):
            confirmar_conclusao(tenant=self.tenant, administrador=admin, agendamento_id=booking.pk)
            confirmar_conclusao(tenant=self.tenant, administrador=admin, agendamento_id=booking.pk)
        booking.refresh_from_db()
        self.assertEqual(booking.conclusao_confirmada_em, self.now)
        self.assertEqual(booking.avaliacao_reputacao.tipo, 'ATRASADO')
        self.assertEqual(processar_retornos(self.now)['enviados'], 1)
        self.assertEqual(ReputacaoCliente.objects.count(), 1)

    def test_completion_permissions_future_and_no_show_are_rejected(self):
        from django.core.exceptions import PermissionDenied
        from agenda.reputation import confirmar_conclusao
        admin = User.objects.create_user('completion-test-admin@example.test', tenant=self.tenant, tipo='ADMIN')
        foreign = User.objects.create_user('foreign-completion@example.test', tenant=self.other, tipo='ADMIN')
        future = self.attendance(days=-1, confirmed=False)
        absent = self.attendance(days=30, status='NAO_COMPARECEU', tipo='AUSENTE', confirmed=False)
        with patch('agenda.reputation.timezone.now', return_value=self.now):
            with self.assertRaises(PermissionDenied):
                confirmar_conclusao(tenant=self.tenant, administrador=foreign, agendamento_id=absent.pk)
            for booking in [future, absent]:
                with self.assertRaises(ValidationError):
                    confirmar_conclusao(tenant=self.tenant, administrador=admin, agendamento_id=booking.pk)

    @patch('whatsapp.evolution.configured', return_value=False)
    def test_complete_view_and_timeline_link_are_scoped(self, configured):
        from agenda.presentation import timeline_payload
        booking = self.attendance(confirmed=False)
        admin = User.objects.create_user('completion-view@example.test', tenant=self.tenant, tipo='ADMIN')
        url = reverse('painel:agendamento_concluir', args=[booking.pk])
        with patch('agenda.reputation.timezone.now', return_value=self.now):
            self.client.force_login(admin)
            timeline = timeline_payload(self.prof, booking.inicio.date(), [])
            self.assertEqual(timeline['appointments'][0]['completeUrl'], url)
            self.assertContains(self.client.get(url, HTTP_HOST='marcos.localhost'), 'Confirmar atendimento realizado')
            response = self.client.post(url, HTTP_HOST='marcos.localhost')
            self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertIsNotNone(booking.conclusao_confirmada_em)
        self.assertEqual(self.client.post(url, HTTP_HOST='outra.localhost').status_code, 403)


class ConcurrentReturnTests(ReturnFixture, TransactionTestCase):
    def setUp(self):
        self.setup_returns()

    def test_two_workers_send_only_once(self):
        self.attendance()
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return processar_retornos(self.now)['enviados']
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: run(), range(2)))
        self.assertEqual(sum(results), 1)
        self.send.assert_called_once()
        self.assertEqual(LembreteRetorno.objects.count(), 1)
