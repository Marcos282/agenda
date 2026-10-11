from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from tenants.models import Tenant
from usuarios.forms import CadastroForm, WhatsAppForm
from usuarios.models import User
from usuarios.validators import normalizar_whatsapp
from agenda.customer_forms import ConfirmarAgendamentoForm
from painel.agendamento_views import AgendamentoPainelForm
from agenda.test_booking import BookingFixture


class WhatsAppTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        self.user = User.objects.create_user('legacy@example.test', 'Strong!Contact2026', tenant=self.tenant)

    def test_required_registration_and_normalized_number(self):
        data = {'email': 'new@example.test', 'password1': 'Strong!Contact2026',
                'password2': 'Strong!Contact2026'}
        form = CadastroForm(data | {'whatsapp': ''}, tenant=self.tenant)
        self.assertFalse(form.is_valid())
        self.assertIn('whatsapp', form.errors)
        form = CadastroForm(data | {'whatsapp': '(11) 99999-1234'}, tenant=self.tenant)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().whatsapp, '+5511999991234')

    def test_registration_accepts_whatsapp_without_phone_format(self):
        form = CadastroForm({
            'email': 'new@example.test', 'password1': 'Strong!Contact2026',
            'password2': 'Strong!Contact2026', 'whatsapp': 'contato sem formato',
        }, tenant=self.tenant)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().whatsapp, 'contato sem formato')

    def test_profile_accepts_whatsapp_without_phone_format(self):
        form = WhatsAppForm({'whatsapp': 'sem formato'}, instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.whatsapp, 'sem formato')

    def test_booking_forms_reject_whatsapp_without_phone_format(self):
        confirmation = ConfirmarAgendamentoForm({
            'whatsapp': 'contato livre', 'nome': 'Cliente',
            'hora': '09:00', 'cotacao': 'quote',
        })
        panel_booking = AgendamentoPainelForm({
            'whatsapp': 'contato livre', 'nome': 'Cliente',
            'oferta': '', 'data': '2026-10-12',
        }, tenant=self.tenant)

        self.assertFalse(confirmation.is_valid())
        self.assertIn('whatsapp', confirmation.errors)
        self.assertFalse(panel_booking.is_valid())
        self.assertIn('whatsapp', panel_booking.errors)

    def test_formats_and_invalid_input(self):
        for value in ['(11) 99999-1234', '11999991234', '5511999991234', '+55 (11) 99999-1234']:
            self.assertEqual(normalizar_whatsapp(value),'+5511999991234')
        self.assertEqual(normalizar_whatsapp('+1 (415) 555-2671'),'+14155552671')
        for value in ['abc11999991234', '+0000000000', '+1111111111', '11 89999-1234']:
            with self.assertRaises(ValidationError): normalizar_whatsapp(value)

    def test_legacy_profile_completion_safe_redirect_and_own_account_only(self):
        response=self.client.post('/login/?next=/agendamentos/',{'email':self.user.email,'password':'Strong!Contact2026'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.url,'/conta/?next=%2Fagendamentos%2F')
        response=self.client.post('/conta/?next=/agendamentos/',{'whatsapp':'(11) 99999-1234','tipo':'ADMIN','tenant_id':'999'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.url,'/agendamentos/')
        self.user.refresh_from_db()
        self.assertEqual(self.user.whatsapp,'+5511999991234')
        self.assertEqual(self.user.tipo,'CLIENTE')
        response=self.client.post('/conta/?next=https://evil.example/',{'whatsapp':'+5511999995678'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.url,'/conta/')
        response=self.client.post('/conta/',{'whatsapp':''},HTTP_HOST='marcos.localhost')
        self.assertIn('whatsapp',response.context['whatsapp_form'].errors)
        self.user.refresh_from_db();self.assertEqual(self.user.whatsapp,'+5511999995678')
        response=self.client.post('/conta/',{'whatsapp':'sem formato'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertEqual(self.user.whatsapp,'sem formato')
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post('/conta/',{'whatsapp':'11999991234'},HTTP_HOST='marcos.localhost').status_code,403)


class BookingContactTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.user.whatsapp='';self.user.save(update_fields=['whatsapp'])

    def test_legacy_customer_must_complete_contact_before_booking(self):
        self.client.force_login(self.user)
        response=self.client.get(self.slots_url(),HTTP_HOST='marcos.localhost')
        self.assertContains(response, 'name="whatsapp"')
        self.assertTrue(response.context['form'].fields['whatsapp'].required)
        with self.assertRaisesMessage(ValidationError,'WhatsApp'): self.book()
        admin=User.objects.create_user('whatsapp-admin@example.test','Strong!Contact2026',tenant=self.tenant,tipo='ADMIN')
        self.client.force_login(admin)
        response=self.client.post(reverse('painel:agendamento_novo'),{'nome':'Cliente teste','oferta':self.offer.pk,'data':self.day.isoformat(),'acao':'consultar'},HTTP_HOST='marcos.localhost')
        self.assertIn('whatsapp',response.context['form'].errors)

    def test_confirmation_requires_valid_contact_and_saves_it(self):
        self.user.whatsapp='+5511999991234';self.user.save(update_fields=['whatsapp'])
        self.client.force_login(self.user)
        response=self.client.post(self.slots_url(),self.payload(whatsapp=''),HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,400)
        self.assertIn('whatsapp',response.context['form'].errors)
        data=self.payload();data.pop('whatsapp')
        self.assertEqual(self.client.post(self.slots_url(),data,HTTP_HOST='marcos.localhost').status_code,400)
        response=self.client.post(self.slots_url(),self.payload(whatsapp='contato livre'),HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,400)
        self.assertIn('whatsapp', response.context['form'].errors)
        response=self.client.post(self.slots_url(),self.payload(whatsapp='(21) 99999-5678'),HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertEqual(self.user.whatsapp,'+5521999995678')
        # A rejected reservation must not silently change the account's contact.
        response=self.client.post(self.slots_url(),self.payload(whatsapp='(31) 99999-5678'),HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,409)
        self.user.refresh_from_db();self.assertEqual(self.user.whatsapp,'+5521999995678')

    def test_legacy_customer_can_complete_contact_in_confirmation(self):
        self.client.force_login(self.user)
        response=self.client.post(self.slots_url(),self.payload(whatsapp='(11) 99999-1234'),HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertEqual(self.user.whatsapp,'+5511999991234')
