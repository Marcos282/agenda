from django.test import TestCase, override_settings
from django.contrib.sessions.backends.db import SessionStore
from tenants.models import Tenant
from usuarios.models import User


@override_settings(DEBUG=True, TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost', 'localhost'])
class CustomerLoginDisabledTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        cls.customer = User.objects.create_user('customer@example.test', 'Senha!9274Teste', tenant=cls.tenant)
        cls.admin = User.objects.create_user('admin@example.test', 'Senha!9274Teste', tenant=cls.tenant, tipo='ADMIN')
        cls.root = User.objects.create_superuser('root@example.test', 'Senha!9274Teste')

    def test_customer_cannot_login_on_platform_or_tenant(self):
        for host in ('localhost', 'marcos.localhost'):
            response = self.client.post('/login/', {'email': self.customer.email, 'password': 'Senha!9274Teste'}, HTTP_HOST=host)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('_auth_user_id', self.client.session)
            self.assertContains(response, 'E-mail ou senha inválidos')
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_old_customer_session_cannot_open_account(self):
        self.client.force_login(self.customer)
        response = self.client.get('/conta/', HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
        self.assertEqual(self.client.get('/loja/', HTTP_HOST='marcos.localhost').status_code, 200)

    def test_customer_signup_redirects_without_creating_account(self):
        count = User.objects.count()
        for method in (self.client.get, self.client.post):
            response = method('/cadastro/', HTTP_HOST='marcos.localhost')
            self.assertRedirects(response, '/loja/', fetch_redirect_response=False)
        self.assertEqual(User.objects.count(), count)

    def test_admin_and_platform_admin_still_login(self):
        for user, host in ((self.admin, 'marcos.localhost'), (self.root, 'localhost')):
            self.client.logout()
            response = self.client.post('/login/', {'email': user.email, 'password': 'Senha!9274Teste'}, HTTP_HOST=host)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_old_customer_handoff_is_rejected(self):
        ticket = SessionStore()
        ticket['login_transfer_user'] = self.customer.pk
        ticket['login_transfer_hash'] = self.customer.get_session_auth_hash()
        ticket.set_expiry(60)
        ticket.create()
        response = self.client.post('/login/continuar/', {'ticket': ticket.session_key}, HTTP_HOST='marcos.localhost', HTTP_ORIGIN='http://localhost')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)
