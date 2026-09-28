from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone as dt_timezone
from threading import Barrier
from zoneinfo import ZoneInfo

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import ProfissionalServico, Servico
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User
from .booking import cancelar, horarios_disponiveis, instante_local, reservar
from .models import Agendamento, Disponibilidade
from .services import configurar_dia, revisao_dia


class BookingFixture:
    def setup_booking(self):
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        self.other = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        self.user = User.objects.create_user('booking@example.test', 'Booking!Password2026', tenant=self.tenant, whatsapp='+5511999991234')
        self.second = User.objects.create_user('second@example.test', 'Booking!Password2026', tenant=self.tenant, whatsapp='+5511999995678')
        self.foreign = User.objects.create_user('foreign@example.test', 'Booking!Password2026', tenant=self.other)
        self.prof = Profissional.objects.create(tenant=self.tenant, nome='João')
        self.service = Servico.objects.create(tenant=self.tenant, nome='Corte')
        self.offer = ProfissionalServico.objects.create(tenant=self.tenant, profissional=self.prof, servico=self.service, valor='40.00', duracao_minutos=40)
        self.day = timezone.localdate(timezone=ZoneInfo(self.tenant.timezone)) + timedelta(days=2)
        self.window = Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day, hora_inicio=time(9,7), hora_fim=time(12,2))
        Disponibilidade.objects.create(tenant=self.tenant, profissional=self.prof, data=self.day, hora_inicio=time(13,11), hora_fim=time(18,23))

    def book(self, hora=time(9,7), **kwargs):
        args = dict(tenant=self.tenant, cliente=self.user, oferta_id=self.offer.pk, dia=self.day, hora=hora,
                    nome='Cliente Teste', valor_exibido='40.00', duracao_exibida=40)
        args.update(kwargs)
        return reservar(**args)

    def slots_url(self):
        return reverse('agenda:horarios', args=[self.offer.pk, self.day.isoformat()])

    def payload(self, **kwargs):
        data = {'whatsapp': '(11) 99999-1234', 'nome': 'Cliente Teste', 'hora': '09:07', 'cotacao': signing.dumps({'oferta': self.offer.pk, 'valor': '40.00', 'duracao': 40}, salt='agendamento')}
        data.update(kwargs)
        return data


class BookingTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()

    def test_real_duration_suggestions_and_snapshot(self):
        self.assertEqual([s['hora'] for s in horarios_disponiveis(self.offer, self.day)][:4], ['09:07', '09:47', '10:27', '11:07'])
        booking = self.book(time(9,13))  # No 15/30-minute business grid.
        self.assertEqual(booking.fim - booking.inicio, timedelta(minutes=40))
        self.assertEqual(booking.inicio, datetime.combine(self.day, time(12,13), tzinfo=dt_timezone.utc))
        self.offer.valor = '65.00'; self.offer.duracao_minutos = 20; self.offer.save()
        self.service.nome='Novo nome'; self.service.save()
        booking.refresh_from_db()
        self.assertEqual(str(booking.valor), '40.00')
        self.assertEqual(booking.servico_nome, 'Corte')
        self.assertEqual(booking.duracao_minutos, 40)

    def test_overlap_adjacency_and_cancel_release(self):
        booking = self.book()
        for hour in [time(9,7), time(9,30), time(9,46)]:
            with self.assertRaises(ValidationError): self.book(hour, cliente=self.second)
        self.book(time(9,47), cliente=self.second)
        self.assertNotIn('09:07', [s['hora'] for s in horarios_disponiveis(self.offer, self.day)])
        cancelar(tenant=self.tenant, cliente=self.user, agendamento_id=booking.pk)
        self.assertIn('09:07', [s['hora'] for s in horarios_disponiveis(self.offer, self.day)])
        self.book()
        self.assertEqual(Agendamento.objects.filter(status='CONFIRMADO').count(),2)

    def test_closed_gap_past_seconds_and_overrun_rejected(self):
        for kwargs in [{'hora':time(12)}, {'hora':time(12,15)}, {'hora':time(18)}, {'hora':time(9,7,1)}, {'dia':self.day+timedelta(days=1)}, {'dia':self.day-timedelta(days=3)}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError): self.book(**kwargs)
        self.assertEqual(Agendamento.objects.count(),0)
        self.assertEqual(horarios_disponiveis(self.offer,self.day+timedelta(days=1)),[])

    def test_price_duration_active_and_tenant_checks(self):
        for changes in [{'valor_exibido':'1.00'}, {'duracao_exibida':1}, {'cliente':self.foreign}]:
            with self.assertRaises(ValidationError): self.book(**changes)
        for obj in [self.prof,self.service,self.offer]:
            obj.ativo=False; obj.save()
            with self.assertRaises(ProfissionalServico.DoesNotExist): self.book()
            obj.ativo=True; obj.save()

    def test_calendar_edits_preserve_bookings_in_both_editors(self):
        self.book()
        periods = list(Disponibilidade.objects.filter(profissional=self.prof,ativo=True))
        with self.assertRaises(ValidationError):
            configurar_dia(tenant=self.tenant, profissional_id=self.prof.pk, data=self.day,periodos=[],revisao=revisao_dia(periods))
        self.window.hora_inicio=time(10)
        with self.assertRaises(ValidationError): self.window.save()
        self.window.refresh_from_db()
        self.assertEqual(self.window.hora_inicio,time(9,7))
        configurar_dia(tenant=self.tenant, profissional_id=self.prof.pk, data=self.day,
            periodos=[(time(9),time(12)),(time(13),time(18))],revisao=revisao_dia(periods))
        self.assertEqual(Disponibilidade.objects.filter(ativo=True).count(),2)

    def test_adjacent_windows_allow_a_service_to_fit(self):
        self.window.hora_fim=time(9,27); self.window.save()
        Disponibilidade.objects.create(tenant=self.tenant,profissional=self.prof,data=self.day,hora_inicio=time(9,27),hora_fim=time(10,7))
        booking = self.book()
        self.assertEqual(booking.fim - booking.inicio, timedelta(minutes=40))

    def test_http_confirmation_private_history_and_csrf(self):
        anon=self.client.get(self.slots_url(),HTTP_HOST='marcos.localhost')
        self.assertContains(anon,'Entrar para agendar')
        self.assertEqual(self.client.post(self.slots_url(),self.payload(),HTTP_HOST='marcos.localhost').status_code,302)
        self.assertFalse(Agendamento.objects.exists())
        self.client.force_login(self.user)
        response=self.client.post(self.slots_url(),self.payload(tenant_id=self.other.pk,cliente_id=self.foreign.pk,valor='0.01'),HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,302)
        booking=Agendamento.objects.get()
        self.assertEqual(booking.cliente,self.user)
        detail=reverse('agenda:detalhe',args=[booking.pk])
        self.assertContains(self.client.get(detail,HTTP_HOST='marcos.localhost'),'Seu horário está reservado')
        self.assertEqual(self.client.post(self.slots_url(),self.payload(),HTTP_HOST='marcos.localhost').status_code,409)
        self.client.force_login(self.second)
        for method in [self.client.get,self.client.post]:
            self.assertEqual(method(detail,HTTP_HOST='marcos.localhost').status_code,404)
        self.assertNotContains(self.client.get(reverse('agenda:meus'),HTTP_HOST='marcos.localhost'),'Cliente Teste')
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post(self.slots_url(),self.payload(),HTTP_HOST='marcos.localhost').status_code,403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(detail,HTTP_HOST='marcos.localhost').status_code,302)
        booking.refresh_from_db();self.assertEqual(booking.status,'CANCELADO')

    def test_routes_quote_and_cross_host_fail_closed(self):
        self.assertEqual(self.client.get(self.slots_url(),HTTP_HOST='wanessa.localhost').status_code,404)
        self.assertEqual(self.client.get(self.slots_url(),HTTP_HOST='localhost').status_code,404)
        self.assertEqual(self.client.get('/agendamentos/servico/1/not-a-date/',HTTP_HOST='marcos.localhost').status_code,404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.slots_url(),self.payload(cotacao='bad'),HTTP_HOST='marcos.localhost').status_code,400)
        quote=self.payload()
        self.offer.valor='55.00';self.offer.save()
        self.assertEqual(self.client.post(self.slots_url(),quote,HTTP_HOST='marcos.localhost').status_code,409)
        self.assertFalse(Agendamento.objects.exists())

    def test_login_next_is_preserved_and_external_redirect_blocked(self):
        url=reverse('login')+'?next='+self.slots_url()
        response=self.client.post(url,{'email':self.user.email,'password':'Booking!Password2026'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.url,self.slots_url())
        self.client.logout()
        response=self.client.post(reverse('login')+'?next=https://evil.example/',{'email':self.user.email,'password':'Booking!Password2026'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.url,reverse('conta'))

    def test_database_constraints_even_without_model_validation(self):
        original=self.book()
        base={field.attname:getattr(original,field.attname) for field in Agendamento._meta.fields if field.name not in ['id','criado_em','atualizado_em']}
        for changes in [{}, {'cliente_id':self.foreign.pk,'inicio':original.inicio+timedelta(hours=1),'fim':original.fim+timedelta(hours=1)}, {'fim':original.fim+timedelta(minutes=1)}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Agendamento.objects.bulk_create([Agendamento(**(base|changes))])

    def test_ambiguous_and_nonexistent_local_times_rejected(self):
        self.tenant.timezone='America/New_York'
        for day,hour in [(datetime(2026,11,1).date(),time(1,30)),(datetime(2027,3,14).date(),time(2,30))]:
            with self.assertRaises(ValidationError): instante_local(day,hour,self.tenant)

    def test_admin_timeline_uses_real_reservations(self):
        booking=self.book()
        admin=User.objects.create_user('admin-booking@example.test','Booking!Password2026',tenant=self.tenant,tipo='ADMIN')
        self.client.force_login(admin)
        response=self.client.get(reverse('painel:agenda'),{'profissional':self.prof.pk,'data':self.day.isoformat()},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.context['timeline']['appointments'][0]['id'],booking.pk)
        self.assertContains(response,'Cliente Teste')
        self.prof.ativo=False;self.prof.save()
        self.assertContains(self.client.get(reverse('painel:agenda'),{'profissional':self.prof.pk,'data':self.day.isoformat()},HTTP_HOST='marcos.localhost'),'Cliente Teste')


class ConcurrentBookingTests(BookingFixture, TransactionTestCase):
    def test_two_simultaneous_customers_only_one_reservation(self):
        self.setup_booking()
        barrier=Barrier(2)
        def worker(user_id):
            close_old_connections()
            try:
                customer=User.objects.get(pk=user_id)
                barrier.wait(timeout=10)
                try:
                    return self.book(cliente=customer).pk
                except ValidationError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(worker,[self.user.pk,self.second.pk]))
        self.assertEqual(sum(result is not None for result in results),1)
        self.assertEqual(Agendamento.objects.filter(status='CONFIRMADO').count(),1)
