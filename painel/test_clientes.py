from datetime import time
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from usuarios.models import User
from agenda.models import Agendamento
from agenda.booking import cancelar, registrar_falta, reservar
from agenda.test_booking import BookingFixture
from .cliente_views import grupos_por_whatsapp


class PanelCustomerTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin=User.objects.create_user('client-list-admin@example.test','Booking!Password2026',tenant=self.tenant,tipo='ADMIN')
        self.client.force_login(self.admin)
        self.url=reverse('painel:clientes')
        self.detail=reverse('painel:cliente_historico',args=[self.user.pk])
        first=self.book(nome='Ana Souza')
        cancelar(tenant=self.tenant,cliente=self.user,agendamento_id=first.pk)
        absent=self.book(time(9,47),nome='Ana Souza')
        with patch('django.utils.timezone.now',return_value=absent.inicio):
            registrar_falta(tenant=self.tenant,administrador=self.admin,agendamento_id=absent.pk)
        self.book(time(10,27),nome='Ana Silva')

    def get(self,path=None,**query):
        return self.client.get(path or self.url,query,HTTP_HOST='marcos.localhost')

    def test_list_contacts_history_totals_and_empty_inactive_customer(self):
        self.second.is_active=False;self.second.save()
        response=self.get()
        self.assertContains(response,'Ana Silva')
        self.assertContains(response,self.user.whatsapp)
        self.assertContains(response,self.second.email)
        self.assertContains(response,'Inativo')
        self.assertNotContains(response,self.foreign.email)
        self.assertNotContains(response,self.admin.email)
        customer=next(c for c in response.context['page_obj'] if c['pk']==self.user.pk)
        self.assertEqual((customer['total'],customer['faltas']),(3,1))
        detail=self.get(self.detail)
        self.assertEqual(detail.context['resumo'],{'total':3,'confirmados':1,'cancelados':1,'faltas':1})
        for label in ['Confirmado','Cancelado','Não compareceu','Ana Souza','Corte']:
            self.assertContains(detail,label)
        self.assertContains(self.get(reverse('painel:cliente_historico',args=[self.second.pk])),'Ainda não há agendamentos')

    def test_search_names_history_email_and_formatted_phone(self):
        for term in ['Ana Souza','Ana Silva',self.user.email,'(11) 99999-1234','+55 (11) 99999-1234','999991234']:
            with self.subTest(term=term):
                response=self.get(q=term)
                self.assertEqual([u['pk'] for u in response.context['page_obj']],[self.user.pk])
        self.user.first_name='Mariana';self.user.last_name='Santos';self.user.save()
        self.assertEqual(self.get(q='Mariana Santos').context['page_obj'].paginator.count,1)
        self.assertContains(self.get(q='inexistente'),'Nenhum cliente encontrado')
        self.assertEqual(self.get(q=self.foreign.email).context['page_obj'].paginator.count,0)

    def test_roles_tenants_and_read_only_access(self):
        self.assertEqual(self.get(reverse('painel:cliente_historico',args=[self.foreign.pk])).status_code,404)
        self.assertEqual(self.client.post(self.url,HTTP_HOST='marcos.localhost').status_code,405)
        self.client.force_login(self.user)
        for url in [self.url,self.detail]:
            self.assertEqual(self.get(url).status_code,403)
        self.client.logout()
        self.assertEqual(self.get().status_code,302)

    def test_pagination_and_role_change_preserve_history(self):
        User.objects.bulk_create([User(email=f'pag{i}@example.test',tenant=self.tenant,first_name='Cliente',password='!') for i in range(21)])
        first=self.get(q='Cliente')
        self.assertEqual(len(first.context['page_obj']),10)
        self.assertContains(first,'q=Cliente&amp;page=2')
        self.assertEqual(len(self.get(q='Cliente',page=2).context['page_obj']),10)
        self.assertEqual(len(self.get(q='Cliente',page=3).context['page_obj']),1)
        self.user.tipo='ADMIN';self.user.save()
        self.assertEqual(self.get(self.detail).context['resumo']['total'],3)
        self.assertEqual(self.get(q=self.user.email).context['page_obj'].paginator.count,1)
        original=Agendamento.objects.filter(cliente=self.user,status='CANCELADO').get()
        fields={f.attname:getattr(original,f.attname) for f in Agendamento._meta.fields if f.name not in ['id','criado_em','atualizado_em']}
        Agendamento.objects.bulk_create([Agendamento(**fields) for _ in range(14)])
        self.assertEqual(len(self.get(self.detail).context['page_obj']),15)
        self.assertEqual(len(self.get(self.detail,page=2).context['page_obj']),2)

    def test_whatsapp_groups_accounts_and_contacts_with_all_statuses(self):
        # This history aggregation scenario needs more than the default daily quota.
        self.tenant.limite_agendamentos_cliente_dia = 10
        self.tenant.save(update_fields=['limite_agendamentos_cliente_dia'])
        from usuarios.models import ContatoCliente
        from agenda.booking import reservar
        phone = self.user.whatsapp
        self.second.whatsapp = phone
        self.second.save()
        self.book(time(11,7), cliente=self.second, nome='Segundo cadastro')
        contact = ContatoCliente.objects.create(tenant=self.tenant, nome='Nome no balcão', whatsapp='(11) 99999-1234')
        duplicate = ContatoCliente.objects.create(tenant=self.tenant, nome='Outro nome antigo', whatsapp=phone)
        booking = reservar(tenant=self.tenant, cliente=None, contato=contact, oferta_id=self.offer.pk,
            dia=self.day, hora=time(13,11), nome='Nome na reserva', valor_exibido='40.00', duracao_exibida=40)
        cancelar(tenant=self.tenant, cliente=None, agendamento_id=booking.pk)
        reservar(tenant=self.tenant, cliente=None, contato=duplicate, oferta_id=self.offer.pk,
            dia=self.day, hora=time(13,51), nome='Outro nome antigo', valor_exibido='40.00', duracao_exibida=40)
        # Another establishment using the same number never enters this customer's totals.
        ContatoCliente.objects.create(tenant=self.other, nome='Contato externo', whatsapp=phone)
        self.foreign.whatsapp = phone
        self.foreign.save()
        expected = {'total': 6, 'confirmados': 3, 'cancelados': 2, 'faltas': 1}
        url = reverse('painel:whatsapp_historico', args=[phone])
        for term in ['', phone, '(11) 99999-1234', 'Nome no balcão', 'Nome na reserva', self.second.email, 'Outro nome antigo']:
            with self.subTest(term=term):
                response = self.get(q=term)
                rows = list(response.context['page_obj'])
                self.assertEqual(len(rows), 1)
                self.assertEqual({key: rows[0][key] for key in expected}, expected)
                self.assertContains(response, url)
                self.assertContains(response, '2 cancelamentos')
                self.assertContains(response, '1 ausência')
        for route in [url, self.detail, reverse('painel:contato_historico', args=[duplicate.pk])]:
            response = self.get(route)
            self.assertEqual(response.context['resumo'], expected)
            self.assertEqual(response.context['page_obj'].paginator.count, 6)
            self.assertNotContains(response, 'Contato externo')
        self.assertEqual(self.get(reverse('painel:whatsapp_historico', args=['11999991234'])).context['resumo'], expected)
        from usuarios.models import ContatoCliente
        unformatted = ContatoCliente.objects.create(
            tenant=self.tenant, nome='Contato sem formato', whatsapp='contato sem formato')
        unformatted_url = reverse('painel:whatsapp_historico', args=[unformatted.whatsapp])
        self.assertEqual(self.get(unformatted_url).status_code, 200)
        self.assertContains(self.get(unformatted_url), 'Contato sem formato')
        self.assertEqual(self.client.post(url, HTTP_HOST='marcos.localhost').status_code, 405)
        self.client.force_login(self.user)
        self.assertEqual(self.get(url).status_code, 403)

    def test_missing_phones_stay_separate_and_pagination_counts_numbers(self):
        from usuarios.models import ContatoCliente
        for i in range(12):
            ContatoCliente.objects.create(tenant=self.tenant, nome=f'Nome {i}', whatsapp=self.user.whatsapp)
        for i in range(2):
            User.objects.create_user(f'no-phone-{i}@example.test', tenant=self.tenant)
        page = self.get().context['page_obj']
        self.assertEqual(page.paginator.count, 4)  # Two numbers and two separate legacy accounts.
        self.assertEqual(sum(row['total'] for row in page), 3)
        self.assertEqual(self.get(q='Nome 11').context['page_obj'].paginator.count, 1)
        self.assertEqual(self.get(q='Nome 11').context['page_obj'][0]['total'], 3)

    def test_unformatted_contact_values_still_group_booking_history(self):
        from usuarios.models import ContatoCliente
        contact = ContatoCliente.objects.create(
            tenant=self.tenant, nome='Contato livre', whatsapp='contato livre')
        with self.assertRaisesMessage(ValidationError, 'Informe um WhatsApp com DDD'):
            reservar(
                tenant=self.tenant, cliente=None, contato=contact, oferta_id=self.offer.pk,
                dia=self.day, hora=time(13, 11), nome='Contato livre',
                valor_exibido='40.00', duracao_exibida=40)

        group = grupos_por_whatsapp(self.tenant, whatsapp='contato livre')

        self.assertEqual(len(group), 1)
        self.assertEqual(group[0]['total'], 0)
