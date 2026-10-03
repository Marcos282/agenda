from datetime import time, timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.management import call_command
from agenda.test_booking import BookingFixture
from agenda.booking import reservar_por_whatsapp, cancelar, registrar_falta
from agenda.models import ReputacaoCliente
from agenda.reputation import avaliar_automaticamente, registrar_atraso, reputacoes, resumir
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost')
class ReputationTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.tenant.limite_agendamentos_cliente_dia = 10
        self.tenant.limite_agendamentos_cliente_futuros = 10
        self.tenant.save()
        self.admin = User.objects.create_user('reputation-admin@example.test', tenant=self.tenant, tipo='ADMIN')

    def guest(self, hour, nome):
        return reservar_por_whatsapp(tenant=self.tenant, nome=nome, whatsapp='(11) 99999-1234',
            oferta_id=self.offer.pk, dia=self.day, hora=hour, valor_exibido='40.00', duracao_exibida=40)

    def test_new_until_exact_third_evaluation_and_names_share_mean(self):
        a = self.guest(time(9,7), 'Marcos')
        b = self.guest(time(9,47), 'Marcos Sousa')
        c = self.guest(time(10,27), 'Marco')
        self.assertEqual(resumir()['rotulo'], 'Cliente Novo')
        with patch('django.utils.timezone.now', return_value=c.fim + timedelta(minutes=1)):
            avaliar_automaticamente(tenant=self.tenant, agendamento_id=a.pk)
            self.assertEqual(reputacoes(self.tenant)[self.user.whatsapp]['rotulo'], 'Cliente Novo')
            avaliar_automaticamente(tenant=self.tenant, agendamento_id=b.pk)
            self.assertIsNone(reputacoes(self.tenant)[self.user.whatsapp]['estrelas'])
            registrar_atraso(tenant=self.tenant, administrador=self.admin, agendamento_id=c.pk)
        result = reputacoes(self.tenant)[self.user.whatsapp]
        self.assertEqual(result['quantidade'], 3)
        self.assertAlmostEqual(result['media'], 11/3)
        self.assertEqual(result['rotulo'], '★★★★')
        self.assertEqual(reputacoes(self.other), {})

    def test_automatic_end_time_idempotence_command_and_correction(self):
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

    def test_cancel_and_absence_points_and_repeat_actions(self):
        cancelled = self.book()
        absent = self.book(time(9,47))
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=cancelled.pk)
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=cancelled.pk)
        with patch('django.utils.timezone.now', return_value=absent.inicio):
            registrar_falta(tenant=self.tenant, administrador=self.admin, agendamento_id=absent.pk)
            registrar_falta(tenant=self.tenant, administrador=self.admin, agendamento_id=absent.pk)
        self.assertEqual(list(ReputacaoCliente.objects.order_by('agendamento_id').values_list('pontuacao',flat=True)), [2,1])

    def test_database_rejects_duplicates_invalid_scores_and_cross_tenant(self):
        booking = self.book()
        values = dict(tenant=self.tenant, agendamento=booking, whatsapp_normalizado=self.user.whatsapp,
            tipo='CONCLUIDO', pontuacao=4)
        ReputacaoCliente.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReputacaoCliente.objects.bulk_create([ReputacaoCliente(**values)])
        other = self.book(time(9,47))
        values['agendamento'] = other
        values['pontuacao'] = 1
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReputacaoCliente.objects.bulk_create([ReputacaoCliente(**values)])
        values.update(pontuacao=4, tenant=self.other)
        with self.assertRaises(ValidationError):
            ReputacaoCliente.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReputacaoCliente.objects.bulk_create([ReputacaoCliente(**values)])

    def test_admin_action_scope_time_post_csrf(self):
        booking = self.book()
        url = reverse('painel:agendamento_atraso', args=[booking.pk])
        with self.assertRaises(ValidationError):
            registrar_atraso(tenant=self.tenant, administrador=self.admin, agendamento_id=booking.pk)
        with self.assertRaises(PermissionDenied):
            registrar_atraso(tenant=self.tenant, administrador=self.user, agendamento_id=booking.pk)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url, HTTP_HOST='marcos.localhost').status_code,200)
        self.assertFalse(ReputacaoCliente.objects.exists())
        with patch('django.utils.timezone.now', return_value=booking.inicio):
            self.assertEqual(self.client.post(url, HTTP_HOST='marcos.localhost').status_code,302)
        self.assertEqual(ReputacaoCliente.objects.get().pontuacao,3)
        professional = User.objects.create_user('rating-professional@example.test', tenant=self.tenant, tipo='PROFISSIONAL')
        self.client.force_login(professional)
        self.assertEqual(self.client.post(url, HTTP_HOST='marcos.localhost').status_code,403)

    def test_tenant_isolation_with_same_number_and_daily_limit_preserved(self):
        from profissionais.models import Profissional
        from catalogo.models import Servico, ProfissionalServico
        from agenda.models import Disponibilidade
        booking = self.book()
        self.foreign.whatsapp = self.user.whatsapp
        self.foreign.save()
        professional = Profissional.objects.create(tenant=self.other, nome='Externo')
        service = Servico.objects.create(tenant=self.other, nome='Corte externo')
        offer = ProfissionalServico.objects.create(tenant=self.other, profissional=professional,
            servico=service, valor='30.00', duracao_minutos=30)
        Disponibilidade.objects.create(tenant=self.other, profissional=professional, data=self.day,
            hora_inicio=time(9), hora_fim=time(12))
        from agenda.booking import reservar
        foreign = reservar(tenant=self.other, cliente=self.foreign, oferta_id=offer.pk, dia=self.day,
            hora=time(9), nome='Mesmo número, outro estabelecimento', valor_exibido='30.00', duracao_exibida=30)
        cancelar(tenant=self.other, cliente=self.foreign, agendamento_id=foreign.pk)
        with patch('django.utils.timezone.now', return_value=booking.fim):
            avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
        self.assertEqual(reputacoes(self.tenant)[self.user.whatsapp]['media'],4)
        self.assertEqual(reputacoes(self.other)[self.user.whatsapp]['media'],2)
        self.tenant.limite_agendamentos_cliente_dia = 1
        self.tenant.save()
        with self.assertRaises(ValidationError):
            self.guest(time(10,27),'Nome diferente')

    def test_late_action_requires_csrf_and_number_normalization_is_shared(self):
        from django.test import Client
        from usuarios.validators import normalizar_whatsapp
        for number in ['(21) 99999-9999','21 99999-9999','21999999999','+55 21 99999-9999']:
            self.assertEqual(normalizar_whatsapp(number),'+5521999999999')
        booking = self.book()
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        response = secure.post(reverse('painel:agendamento_atraso',args=[booking.pk]), HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,403)
        self.assertFalse(ReputacaoCliente.objects.exists())

    def test_stars_thresholds(self):
        for average, stars in [(4,4),(3.67,4),(3.49,3),(3.2,3),(2.5,3),(2.49,2),(1.5,2),(1,1)]:
            self.assertEqual(resumir(3,average)['estrelas'],stars)
            self.assertEqual(resumir(2,average)['rotulo'],'Cliente Novo')

    def test_list_history_and_agenda_show_same_reputation(self):
        bookings = [self.guest(time(9,7),'Marcos'), self.guest(time(9,47),'Marcos Sousa'), self.guest(time(10,27),'Marco')]
        self.client.force_login(self.admin)
        with patch('django.utils.timezone.now', return_value=bookings[-1].fim):
            listing = self.client.get(reverse('painel:clientes'), HTTP_HOST='marcos.localhost')
            group = next(g for g in listing.context['page_obj'] if g['whatsapp']==self.user.whatsapp)
            self.assertEqual(group['nome_exibicao'],'Marco')
            self.assertEqual(group['reputacao']['quantidade'],3)
            self.assertContains(listing,'aria-label="4 de 4 estrelas"')
            history = self.client.get(reverse('painel:whatsapp_historico',args=[self.user.whatsapp]), HTTP_HOST='marcos.localhost')
            self.assertContains(history,'+4')
            agenda = self.client.get(reverse('painel:agenda'), {'profissional':self.prof.pk,'data':self.day.isoformat()}, HTTP_HOST='marcos.localhost')
            self.assertEqual(agenda.context['timeline']['appointments'][0]['reputacao']['rotulo'],'★★★★')

    def test_new_label_is_visible_on_list_history_and_agenda_until_third_rating(self):
        bookings = [self.guest(hour, 'Cliente com nome extenso') for hour in
            [time(9,7), time(9,47), time(10,27), time(11,7)]]
        self.client.force_login(self.admin)
        for quantity in range(4):
            if quantity:
                cancelar(tenant=self.tenant, cliente=None, agendamento_id=bookings[quantity-1].pk)
            listing = self.client.get(reverse('painel:clientes'), HTTP_HOST='marcos.localhost')
            group = next(g for g in listing.context['page_obj'] if g['whatsapp']==self.user.whatsapp)
            self.assertEqual(group['reputacao']['quantidade'],quantity)
            history = self.client.get(reverse('painel:whatsapp_historico',args=[self.user.whatsapp]), HTTP_HOST='marcos.localhost')
            agenda = self.client.get(reverse('painel:agenda'), {'profissional':self.prof.pk,'data':self.day.isoformat()}, HTTP_HOST='marcos.localhost')
            rating = agenda.context['timeline']['appointments'][0]['reputacao']
            if quantity < 3:
                self.assertEqual(rating['rotulo'],'Cliente Novo')
                for response in [listing,history,agenda]:
                    self.assertContains(response,'Cliente Novo')
                    self.assertContains(response,'client-reputation-new')
                self.assertIsNone(rating['estrelas'])
            else:
                self.assertEqual(rating['rotulo'],'★★☆☆')
                self.assertNotContains(history,'client-reputation-new')

    def test_snapshot_identity_survives_account_phone_change(self):
        booking = self.book()
        old = self.user.whatsapp
        self.user.whatsapp = '+5521999991234'
        self.user.save()
        with patch('django.utils.timezone.now', return_value=booking.fim):
            avaliar_automaticamente(tenant=self.tenant, agendamento_id=booking.pk)
        self.assertIn(old, reputacoes(self.tenant))
        self.assertNotIn(self.user.whatsapp, reputacoes(self.tenant))
