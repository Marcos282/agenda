from datetime import time
from django.core import signing
from django.test import Client, TestCase
from django.urls import reverse
from agenda.test_booking import BookingFixture
from agenda.models import Agendamento
from usuarios.models import User


class PanelBookingTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('panel-booking@example.test', 'Booking!Password2026', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.url = reverse('painel:agendamento_novo')

    def data(self, **changes):
        return dict(whatsapp='(11) 99999-1234', nome='Cliente do balcão', oferta=self.offer.pk, data=self.day.isoformat(), **changes)

    def post(self, data):
        return self.client.post(self.url, data, HTTP_HOST='marcos.localhost')

    def quote(self):
        return signing.dumps({'oferta':self.offer.pk, 'valor':'40.00', 'duracao':40}, salt='agendamento-painel')

    def test_admin_creates_booking_for_customer_and_returns_to_agenda(self):
        response=self.post(self.data(acao='consultar'))
        self.assertContains(response,'09:07')
        self.assertFalse(response.context['selecionando'])
        self.assertNotContains(response, 'placeholder="Nome completo do cliente"')
        self.assertNotContains(response, 'class="edit-form"')
        self.assertFalse(Agendamento.objects.exists())
        response=self.post(self.data(acao='confirmar',hora='09:07',cotacao=self.quote()))
        self.assertEqual(response.status_code,302)
        self.assertIn('/painel/agenda/',response.url)
        booking=Agendamento.objects.get()
        self.assertIsNone(booking.cliente)
        self.assertEqual(booking.contato.whatsapp,'+5511999991234')
        self.assertNotEqual(booking.cliente,self.admin)
        self.assertEqual(booking.cliente_nome,'Cliente do balcão')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('agenda:meus'),HTTP_HOST='marcos.localhost').context['agendamentos'].paginator.count,0)

    def test_permission_scope_csrf_and_tampering(self):
        page=self.client.get(self.url,HTTP_HOST='marcos.localhost')
        self.assertNotContains(page,self.foreign.email)
        payload=self.data(acao='confirmar',hora='09:07',cotacao=self.quote())
        for value in ['', '123']:
            self.assertEqual(self.post(payload|{'whatsapp':value}).status_code,400)
        self.assertEqual(self.post(payload|{'cotacao':'bad'}).status_code,400)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(self.url,payload,HTTP_HOST='marcos.localhost').status_code,403)
        self.client.force_login(self.user)
        self.assertEqual(self.post(payload).status_code,403)
        self.client.logout()
        self.assertEqual(self.post(payload).status_code,302)
        self.assertFalse(Agendamento.objects.exists())

    def test_conflict_stale_price_closed_day_and_edit(self):
        self.book(time(9,7))
        payload=self.data(acao='confirmar',hora='09:07',cotacao=self.quote())
        self.assertEqual(self.post(payload).status_code,409)
        self.assertEqual(self.post(payload|{'hora':'12:15'}).status_code,409)
        self.offer.valor='55.00';self.offer.save()
        self.assertEqual(self.post(payload|{'hora':'13:11'}).status_code,409)
        page=self.post(payload|{'acao':'editar'})
        self.assertTrue(page.context['selecionando'])
        self.assertEqual(page.context['form']['nome'].value(), 'Cliente do balcão')
        self.assertEqual(Agendamento.objects.count(),1)

    def test_preserves_day_professional_and_requires_active_customer(self):
        page=self.client.get(self.url,{'profissional':self.prof.pk,'data':self.day.isoformat()},HTTP_HOST='marcos.localhost')
        self.assertEqual(page.context['form'].initial['oferta'],self.offer.pk)
        self.assertEqual(page.context['form'].initial['data'],self.day.isoformat())
        self.user.is_active=False;self.user.save()
        self.assertEqual(self.post(self.data(acao='consultar')).status_code,200)

    def test_admin_cancel_confirmation_history_and_release(self):
        from agenda.booking import horarios_disponiveis
        booking=self.book()
        url=reverse('painel:agendamento_cancelar',args=[booking.pk])
        self.assertContains(self.client.get(url,HTTP_HOST='marcos.localhost'),'Confirmar cancelamento')
        booking.refresh_from_db();self.assertEqual(booking.status,'CONFIRMADO')
        response=self.client.post(url,{'cliente':self.foreign.pk},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,302)
        self.assertIn(self.day.isoformat(),response.url)
        booking.refresh_from_db();self.assertEqual(booking.status,'CANCELADO')
        self.assertIsNotNone(booking.cancelado_em)
        self.assertEqual(Agendamento.objects.count(),1)
        self.assertIn('09:07',[s['hora'] for s in horarios_disponiveis(self.offer,self.day)])
        cancelled_at=booking.cancelado_em
        self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,302)
        booking.refresh_from_db();self.assertEqual(booking.cancelado_em,cancelled_at)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('agenda:meus'),HTTP_HOST='marcos.localhost'),'Cancelado')

    def test_admin_cancel_permissions_csrf_and_other_tenant(self):
        from django.core.exceptions import PermissionDenied
        from agenda.booking import cancelar_pelo_painel
        booking=self.book()
        url=reverse('painel:agendamento_cancelar',args=[booking.pk])
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(url,HTTP_HOST='marcos.localhost').status_code,403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,403)
        with self.assertRaises(PermissionDenied):
            cancelar_pelo_painel(tenant=self.tenant,administrador=self.user,agendamento_id=booking.pk)
        foreign_admin=User.objects.create_user('foreign-admin@example.test','Booking!Password2026',tenant=self.other,tipo='ADMIN')
        self.client.force_login(foreign_admin)
        for method in [self.client.get,self.client.post]:
            self.assertEqual(method(url,HTTP_HOST='wanessa.localhost').status_code,404)
        booking.refresh_from_db();self.assertEqual(booking.status,'CONFIRMADO')

    def test_admin_cannot_cancel_started_appointment(self):
        from unittest.mock import patch
        booking=self.book()
        url=reverse('painel:agendamento_cancelar',args=[booking.pk])
        with patch('django.utils.timezone.now',return_value=booking.inicio):
            self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,409)
        booking.refresh_from_db();self.assertEqual(booking.status,'CONFIRMADO')

    def test_no_show_confirmation_history_and_duplicate(self):
        from unittest.mock import patch
        booking=self.book()
        url=reverse('painel:agendamento_falta',args=[booking.pk])
        with patch('django.utils.timezone.now',return_value=booking.inicio):
            response=self.client.get(url,HTTP_HOST='marcos.localhost')
            self.assertContains(response,'Confirmar falta')
            booking.refresh_from_db();self.assertEqual(booking.status,'CONFIRMADO')
            self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,302)
            booking.refresh_from_db();self.assertEqual(booking.status,'NAO_COMPARECEU')
            self.assertEqual(booking.nao_compareceu_em,booking.inicio)
            self.assertIsNone(booking.cancelado_em)
            self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,302)
            page=self.client.get(reverse('painel:agenda'),{'profissional':self.prof.pk,'data':self.day.isoformat()},HTTP_HOST='marcos.localhost')
            self.assertContains(page,'Não compareceu')
            self.assertIsNone(page.context['timeline']['appointments'][0]['noShowUrl'])
            self.assertIsNone(page.context['timeline']['appointments'][0]['cancelUrl'])
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('agenda:detalhe',args=[booking.pk]),HTTP_HOST='marcos.localhost'),'Não compareceu')
        self.assertEqual(self.client.post(reverse('agenda:detalhe',args=[booking.pk]),HTTP_HOST='marcos.localhost').status_code,409)
        booking.refresh_from_db();self.assertEqual(booking.status,'NAO_COMPARECEU')

    def test_no_show_rejects_future_cancelled_foreign_and_client(self):
        from unittest.mock import patch
        from django.core.exceptions import PermissionDenied
        from agenda.booking import registrar_falta
        booking=self.book()
        url=reverse('painel:agendamento_falta',args=[booking.pk])
        self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,409)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(url,HTTP_HOST='marcos.localhost').status_code,403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,403)
        with self.assertRaises(PermissionDenied):
            registrar_falta(tenant=self.tenant,administrador=self.user,agendamento_id=booking.pk)
        foreign_admin=User.objects.create_user('foreign-noshow@example.test','Booking!Password2026',tenant=self.other,tipo='ADMIN')
        self.client.force_login(foreign_admin)
        self.assertEqual(self.client.post(url,HTTP_HOST='wanessa.localhost').status_code,404)
        self.client.force_login(self.admin)
        self.client.post(reverse('painel:agendamento_cancelar',args=[booking.pk]),HTTP_HOST='marcos.localhost')
        with patch('django.utils.timezone.now',return_value=booking.inicio):
            self.assertEqual(self.client.post(url,HTTP_HOST='marcos.localhost').status_code,409)
        booking.refresh_from_db();self.assertEqual(booking.status,'CANCELADO')
        self.assertIsNone(booking.nao_compareceu_em)

    def test_text_contact_required_reused_and_listed_without_account(self):
        from usuarios.models import ContatoCliente
        from agenda.booking import reservar_pelo_painel, cancelar_pelo_painel
        accounts=User.objects.count()
        page=self.client.get(self.url,HTTP_HOST='marcos.localhost')
        self.assertContains(page,'type="text" name="nome"')
        self.assertNotContains(page,'<select name="cliente"')
        for change in [{'nome':''},{'whatsapp':''},{'whatsapp':'123'}]:
            self.assertEqual(self.post(self.data(acao='consultar')|change).status_code,400)
        args=dict(tenant=self.tenant,administrador=self.admin,nome='  João   Silva ',whatsapp='(11) 99999-1234',
            oferta_id=self.offer.pk,dia=self.day,hora=time(9,7),valor_exibido='40.00',duracao_exibida=40)
        first=reservar_pelo_painel(**args)
        second=reservar_pelo_painel(**(args|{'nome':'joão silva','hora':time(9,47)}))
        self.assertEqual(first.contato_id,second.contato_id)
        self.assertEqual(ContatoCliente.objects.count(),1)
        self.assertEqual(User.objects.count(),accounts)
        self.assertEqual(first.whatsapp_contato,'+5511999991234')
        cancelar_pelo_painel(tenant=self.tenant,administrador=self.admin,agendamento_id=first.pk)
        page=self.client.get(reverse('painel:clientes'),{'q':'João Silva'},HTTP_HOST='marcos.localhost')
        self.assertEqual(page.context['page_obj'].paginator.count,1)
        self.assertEqual(page.context['page_obj'][0]['total'],2)
        detail=reverse('painel:contato_historico',args=[first.contato_id])
        page=self.client.get(detail,HTTP_HOST='marcos.localhost')
        self.assertEqual(page.context['resumo']['total'],2)
        self.assertContains(page,'Cancelado')
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(detail,HTTP_HOST='wanessa.localhost').status_code,403)

    def test_failed_guest_booking_rolls_back_contact_and_foreign_ids_ignored(self):
        from usuarios.models import ContatoCliente
        payload=self.data(acao='confirmar',hora='12:15',cotacao=self.quote())
        self.assertEqual(self.post(payload).status_code,409)
        self.assertEqual(ContatoCliente.objects.count(),0)
        foreign=ContatoCliente.objects.create(tenant=self.other,nome='Outra pessoa',whatsapp='11999991234')
        payload.update(hora='09:07',cliente=self.foreign.pk,contato=foreign.pk,tenant_id=self.other.pk)
        self.assertEqual(self.post(payload).status_code,302)
        booking=Agendamento.objects.get()
        self.assertIsNone(booking.cliente_id)
        self.assertEqual(booking.contato.tenant_id,self.tenant.pk)
        self.assertNotEqual(booking.contato_id,foreign.pk)
