from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.booking import cancelar, reservar_por_whatsapp, registrar_falta
from agenda.models import Agendamento, ReputacaoCliente, ReputacaoClienteAuditoria
from agenda.reputation import (
    PONTOS,
    avaliar_automaticamente,
    calculate_customer_reputation,
    corrigir_avaliacao,
    registrar_atraso,
    reputacoes,
    resumir,
)
from agenda.test_booking import BookingFixture
from catalogo.models import ProfissionalServico, Servico
from profissionais.models import Profissional
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost')
class ReputationTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.tenant.limite_agendamentos_cliente_dia = 30
        self.tenant.limite_agendamentos_cliente_futuros = 30
        self.tenant.save()
        self.admin = User.objects.create_user('reputation-admin@example.test', tenant=self.tenant, tipo='ADMIN')

    def guest(self, hour, nome='Cliente Teste'):
        return reservar_por_whatsapp(
            tenant=self.tenant,
            nome=nome,
            whatsapp='(11) 99999-1234',
            oferta_id=self.offer.pk,
            dia=self.day,
            hora=hour,
            valor_exibido='40.00',
            duracao_exibida=40,
        )

    def create_booking(self, start, *, tenant=None, customer=None, offer=None, status='CONFIRMADO'):
        tenant = tenant or self.tenant
        customer = customer or self.user
        offer = offer or self.offer
        return Agendamento.objects.create(
            tenant=tenant,
            cliente=customer,
            oferta=offer,
            profissional=offer.profissional,
            cliente_nome='Cliente Teste',
            cliente_whatsapp=customer.whatsapp,
            servico_nome=offer.servico.nome,
            profissional_nome=offer.profissional.nome,
            inicio=start,
            fim=start + timedelta(minutes=40),
            valor='40.00',
            duracao_minutos=40,
            status=status,
            cancelado_em=start if status == 'CANCELADO' else None,
            nao_compareceu_em=start if status == 'NAO_COMPARECEU' else None,
        )

    def record(self, tipo, *, days_ago=1, tenant=None, customer=None, offer=None):
        start = timezone.now() - timedelta(days=days_ago)
        status = 'CANCELADO' if tipo == 'DESMARCOU' else 'NAO_COMPARECEU' if tipo == 'AUSENTE' else 'CONFIRMADO'
        booking = self.create_booking(start, tenant=tenant, customer=customer, offer=offer, status=status)
        rating = ReputacaoCliente.objects.create(
            tenant=booking.tenant,
            agendamento=booking,
            whatsapp_normalizado=booking.cliente_whatsapp,
            data_atendimento=booking.inicio,
            tipo=tipo,
            pontuacao=PONTOS[tipo],
        )
        return booking, rating

    def future_record(self, tipo='CONCLUIDO'):
        start = timezone.now() + timedelta(days=2)
        return self.record_at(start, tipo)

    def record_at(self, start, tipo):
        status = 'CANCELADO' if tipo == 'DESMARCOU' else 'NAO_COMPARECEU' if tipo == 'AUSENTE' else 'CONFIRMADO'
        booking = self.create_booking(start, status=status)
        return ReputacaoCliente.objects.create(
            tenant=self.tenant,
            agendamento=booking,
            whatsapp_normalizado=booking.cliente_whatsapp,
            data_atendimento=booking.inicio,
            tipo=tipo,
            pontuacao=PONTOS[tipo],
        )

    def test_no_evaluations_and_one_or_two_are_new(self):
        self.assertEqual(calculate_customer_reputation(self.user, self.tenant)['quantidade'], 0)
        self.assertEqual(calculate_customer_reputation(self.user, self.tenant)['nota'], None)
        for count in (1, 2):
            self.record('CONCLUIDO', days_ago=count)
            result = calculate_customer_reputation(self.user, self.tenant)
            self.assertEqual(result['quantidade'], count)
            self.assertFalse(result['disponivel'])
            self.assertEqual(result['rotulo'], 'Cliente Novo — Reputação em formação')

    def test_third_evaluation_is_scored_and_identity_uses_normalized_whatsapp(self):
        for days_ago in (1, 2):
            self.record('CONCLUIDO', days_ago=days_ago)
        self.assertFalse(calculate_customer_reputation(self.user, self.tenant)['disponivel'])
        self.record('ATRASADO', days_ago=3)
        result = calculate_customer_reputation(self.user.whatsapp, self.tenant)
        self.assertTrue(result['disponivel'])
        self.assertEqual(result['quantidade'], 3)
        self.assertEqual(result['media'], Decimal('3.666666666666666666666666667'))
        self.assertEqual(result['nota'], Decimal('3.67'))
        self.assertEqual((result['pontuais'], result['atrasos'], result['faltas']), (2, 1, 0))

    def test_formula_with_more_than_five_events_uses_unrounded_source_scores(self):
        outcomes = ['CONCLUIDO'] * 13 + ['ATRASADO', 'AUSENTE'] + [
            'CONCLUIDO', 'CONCLUIDO', 'CONCLUIDO', 'ATRASADO', 'CONCLUIDO',
        ]
        for index, outcome in enumerate(outcomes):
            self.record(outcome, days_ago=len(outcomes) - index)
        result = calculate_customer_reputation(self.user, self.tenant)
        self.assertEqual(result['quantidade'], 20)
        self.assertEqual(result['media_historica'], Decimal('3.7'))
        self.assertEqual(result['media_recente'], Decimal('3.8'))
        self.assertEqual(result['media'], Decimal('3.770'))
        self.assertEqual(result['nota'], Decimal('3.77'))
        self.assertEqual((result['pontuais'], result['atrasos'], result['faltas']), (17, 2, 1))

    def test_reputation_preserves_nonstandard_contact_identity(self):
        self.user.whatsapp = 'contato 123'
        self.user.save()
        for days_ago in (1, 2, 3):
            booking = self.create_booking(timezone.now() - timedelta(days=days_ago))
            rating = avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
            self.assertEqual(rating.whatsapp_normalizado, self.user.whatsapp)
            self.assertEqual(rating.data_atendimento, booking.inicio)
        result = calculate_customer_reputation(self.user, self.tenant)
        self.assertEqual(result['quantidade'], 3)
        self.assertEqual(result['nota'], Decimal('4.00'))
        self.assertEqual(reputacoes(self.tenant)[self.user.whatsapp], result)

    def test_all_punctual_attendances_receive_four_stars_and_show_count(self):
        for days_ago in (1, 2, 3):
            self.record('CONCLUIDO', days_ago=days_ago)
        result = calculate_customer_reputation(self.user, self.tenant)
        self.assertEqual(result['media'], Decimal('4'))
        self.assertEqual(result['nota'], Decimal('4.00'))
        self.assertEqual(result['preenchimentos'], [100, 100, 100, 100])
        self.assertEqual(result['quantidade'], 3)

    def test_lateness_absence_and_half_star_visualization(self):
        self.record('CONCLUIDO', days_ago=3)
        self.record('ATRASADO', days_ago=2)
        self.record('AUSENTE', days_ago=1)
        result = calculate_customer_reputation(self.user, self.tenant)
        self.assertEqual(result['media'], Decimal('2.333333333333333333333333333'))
        self.assertEqual(result['nota'], Decimal('2.33'))
        self.assertEqual(result['preenchimentos'], [100, 100, 33, 0])
        self.assertEqual((result['pontuais'], result['atrasos'], result['faltas']), (1, 1, 1))
        _, absence = self.record('AUSENTE', days_ago=4)
        self.assertEqual(absence.pontuacao, 0)

    def test_recent_improvement_increases_rating_without_erasing_old_history(self):
        for days_ago in range(10, 5, -1):
            self.record('AUSENTE', days_ago=days_ago)
        before = calculate_customer_reputation(self.user, self.tenant)
        for days_ago in range(5, 0, -1):
            self.record('CONCLUIDO', days_ago=days_ago)
        after = calculate_customer_reputation(self.user, self.tenant)
        self.assertEqual(before['media'], Decimal('0'))
        self.assertEqual(after['media_historica'], Decimal('2'))
        self.assertEqual(after['media_recente'], Decimal('4'))
        self.assertEqual(after['media'], Decimal('3.4'))
        self.assertEqual(ReputacaoCliente.objects.for_tenant(self.tenant).count(), 10)

    def test_future_pending_unrated_and_allowed_cancellation_do_not_affect_rating(self):
        self.future_record()
        future_cancel = self.guest(time(9, 7))
        cancelar(tenant=self.tenant, cliente=None, agendamento_id=future_cancel.pk)
        self.record('CONCLUIDO', days_ago=1)
        self.record('CONCLUIDO', days_ago=2)
        self.assertFalse(calculate_customer_reputation(self.user, self.tenant)['disponivel'])
        self.record('CONCLUIDO', days_ago=3)
        self.record_at(timezone.now() - timedelta(days=3), 'DESMARCOU')
        result = calculate_customer_reputation(self.user, self.tenant)
        self.assertEqual(result['quantidade'], 3)
        self.assertEqual(result['nota'], Decimal('4.00'))
        self.assertEqual(ReputacaoCliente.objects.filter(tipo='DESMARCOU').count(), 2)

    def test_correction_updates_single_event_and_keeps_audit_with_responsible_admin(self):
        booking, rating = self.record('CONCLUIDO')
        corrected = corrigir_avaliacao(
            tenant=self.tenant, administrador=self.admin, agendamento_id=booking.pk, tipo='ATRASADO',
        )
        self.assertEqual(corrected.pk, rating.pk)
        self.assertEqual(corrected.pontuacao, 3)
        audit = ReputacaoClienteAuditoria.objects.get(reputacao=rating)
        self.assertEqual((audit.tipo_anterior, audit.pontuacao_anterior), ('CONCLUIDO', 4))
        self.assertEqual((audit.tipo_novo, audit.pontuacao_nova), ('ATRASADO', 3))
        self.assertEqual(audit.alterado_por, self.admin)
        self.assertEqual(ReputacaoCliente.objects.filter(agendamento=booking).count(), 1)

    def test_automatic_completion_is_idempotent_and_manual_correction_is_preserved(self):
        booking = self.book()
        self.assertIsNone(avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk))
        with patch('django.utils.timezone.now', return_value=booking.fim):
            first = avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
            second = avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
            call_command('atualizar_reputacoes', verbosity=0)
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(first.pontuacao, 4)
            registrar_atraso(tenant=self.tenant, administrador=self.admin, agendamento_id=booking.pk)
            avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
        self.assertEqual(ReputacaoCliente.objects.count(), 1)
        self.assertEqual(ReputacaoCliente.objects.get().pontuacao, 3)
        self.assertEqual(ReputacaoClienteAuditoria.objects.get().alterado_por, self.admin)

    def test_manual_absence_and_permitted_cancellation_keep_occurrence_history(self):
        cancelled = self.book()
        absent = self.book(time(9, 47))
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=cancelled.pk)
        with patch('django.utils.timezone.now', return_value=absent.fim):
            registrar_falta(tenant=self.tenant, administrador=self.admin, agendamento_id=absent.pk)
        self.assertEqual(
            list(ReputacaoCliente.objects.order_by('agendamento_id').values_list('tipo', 'pontuacao')),
            [('DESMARCOU', 2), ('AUSENTE', 0)],
        )
        self.assertEqual(calculate_customer_reputation(self.user, self.tenant)['quantidade'], 0)

    def test_tenant_isolation_for_identical_whatsapp(self):
        self.foreign.whatsapp = self.user.whatsapp
        self.foreign.save()
        other_prof = Profissional.objects.create(tenant=self.other, nome='Externo')
        other_service = Servico.objects.create(tenant=self.other, nome='Serviço externo')
        other_offer = ProfissionalServico.objects.create(
            tenant=self.other, profissional=other_prof, servico=other_service, valor='30.00', duracao_minutos=40,
        )
        self.record('CONCLUIDO')
        self.record('CONCLUIDO', days_ago=2)
        self.record('CONCLUIDO', days_ago=3)
        self.record('AUSENTE', days_ago=1, tenant=self.other, customer=self.foreign, offer=other_offer)
        with patch('agenda.reputation.timezone.now', return_value=timezone.now() + timedelta(days=2)):
            local = calculate_customer_reputation(self.user, self.tenant)
            external = calculate_customer_reputation(self.foreign, self.other)
        self.assertEqual(local['nota'], Decimal('4.00'))
        self.assertEqual(external['nota'], None)
        self.assertEqual(reputacoes(self.other)[self.user.whatsapp]['quantidade'], 1)

    def test_database_rejects_duplicate_or_cross_tenant_evaluations(self):
        booking, _ = self.record('CONCLUIDO')
        values = dict(
            tenant=self.tenant,
            agendamento=booking,
            whatsapp_normalizado=self.user.whatsapp,
            data_atendimento=booking.inicio,
            tipo='CONCLUIDO',
            pontuacao=4,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReputacaoCliente.objects.bulk_create([ReputacaoCliente(**values)])
        other_booking = self.book(time(9, 47))
        values.update(tenant=self.other, agendamento=other_booking)
        with self.assertRaises(ValidationError):
            ReputacaoCliente.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReputacaoCliente.objects.bulk_create([ReputacaoCliente(**values)])

    def test_admin_correction_is_tenant_scoped_and_post_only(self):
        booking, _ = self.record('CONCLUIDO')
        url = reverse('painel:corrigir_reputacao', args=[booking.pk])
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url, HTTP_HOST='marcos.localhost').status_code, 405)
        self.assertEqual(self.client.post(url, {'tipo': 'ATRASADO'}, HTTP_HOST='marcos.localhost').status_code, 302)
        self.assertEqual(ReputacaoClienteAuditoria.objects.get().alterado_por, self.admin)
        history = self.client.get(
            reverse('painel:whatsapp_historico', args=[self.user.whatsapp]),
            HTTP_HOST='marcos.localhost',
        )
        self.assertContains(history, 'Correção em')
        self.assertContains(history, 'Compareceu')
        foreign_admin = User.objects.create_user('foreign-admin@example.test', tenant=self.other, tipo='ADMIN')
        self.client.force_login(foreign_admin)
        self.assertEqual(self.client.post(url, {'tipo': 'AUSENTE'}, HTTP_HOST='wanessa.localhost').status_code, 404)

    def test_admin_action_permissions_and_number_normalization(self):
        for number in ['(21) 99999-9999', '21 99999-9999', '21999999999', '+55 21 99999-9999']:
            from usuarios.validators import normalizar_whatsapp
            self.assertEqual(normalizar_whatsapp(number), '+5521999999999')
        booking = self.book()
        with self.assertRaises(ValidationError):
            registrar_atraso(tenant=self.tenant, administrador=self.admin, agendamento_id=booking.pk)
        with self.assertRaises(PermissionDenied):
            registrar_atraso(tenant=self.tenant, administrador=self.user, agendamento_id=booking.pk)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        response = secure.post(
            reverse('painel:agendamento_atraso', args=[booking.pk]),
            HTTP_HOST='marcos.localhost',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReputacaoCliente.objects.exists())

    def test_customer_list_and_history_render_score_counts_and_formula(self):
        for days_ago in (1, 2, 3):
            self.record('CONCLUIDO', days_ago=days_ago)
        self.client.force_login(self.admin)
        listing = self.client.get(reverse('painel:clientes'), HTTP_HOST='marcos.localhost')
        group = next(row for row in listing.context['page_obj'] if row['whatsapp'] == self.user.whatsapp)
        self.assertEqual(group['reputacao']['nota'], Decimal('4.00'))
        self.assertContains(listing, '4,00/4')
        history = self.client.get(
            reverse('painel:whatsapp_historico', args=[self.user.whatsapp]),
            HTTP_HOST='marcos.localhost',
        )
        self.assertContains(history, '70%')
        self.assertContains(history, 'Pontuais: 3')
        self.assertContains(history, '4,00/4')

    def test_new_customer_label_remains_until_third_valid_evaluation(self):
        for index in range(2):
            self.record('CONCLUIDO', days_ago=index + 1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('painel:clientes'), HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'Cliente Novo — Reputação em formação')
        self.record('CONCLUIDO', days_ago=3)
        response = self.client.get(reverse('painel:clientes'), HTTP_HOST='marcos.localhost')
        self.assertContains(response, '4,00/4')
        self.assertContains(response, '3 avaliações')

    def test_old_number_snapshot_survives_account_phone_change(self):
        booking = self.book()
        old = self.user.whatsapp
        self.user.whatsapp = '+5521999991234'
        self.user.save()
        with patch('django.utils.timezone.now', return_value=booking.fim):
            avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
            self.assertIn(old, reputacoes(self.tenant))
            self.assertNotIn(self.user.whatsapp, reputacoes(self.tenant))


class ReputationSummaryTests(TestCase):
    def test_decimal_output_rounds_only_display_value(self):
        result = resumir(3, Decimal('3.765'))
        self.assertEqual(result['media'], Decimal('3.765'))
        self.assertEqual(result['nota'], Decimal('3.77'))
        self.assertEqual(resumir(2, Decimal('4'))['nota'], None)
