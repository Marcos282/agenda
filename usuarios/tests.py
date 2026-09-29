from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from tenants.models import Tenant
from .models import Cliente

User = get_user_model()
PASSWORD = 'Segredo-Forte!2026_az'


class FoundationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marcos = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        cls.wanessa = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        cls.sofia = Tenant.objects.create(nome='Sofia', subdomain='sofia')
        cls.user = User.objects.create_user('cliente@exemplo.com', PASSWORD, tenant=cls.marcos)

    def post_login(self, host='marcos.localhost', **extra):
        return self.client.post(reverse('login'), {'email': self.user.email, 'password': PASSWORD, **extra}, HTTP_HOST=host)

    def test_each_host_resolves_its_tenant(self):
        for tenant in (self.marcos, self.wanessa, self.sofia):
            with self.subTest(tenant=tenant.subdomain):
                response = self.client.get('/', HTTP_HOST=f'{tenant.subdomain}.localhost:8000')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.wsgi_request.tenant, tenant)
                self.assertContains(response, tenant.nome)

    def test_unknown_nested_inactive_and_untrusted_hosts(self):
        for host in ['desconhecido.localhost', 'marcos.sofia.localhost', 'bad-.localhost']:
            self.assertEqual(self.client.get('/', HTTP_HOST=host).status_code, 404)
        self.assertEqual(self.client.get('/', HTTP_HOST='marcos.localhost.evil.test').status_code, 400)
        Tenant.objects.filter(pk=self.marcos.pk).update(ativo=False)
        for path in ['/', '/cadastro/', '/login/', '/conta/']:
            self.assertEqual(self.client.get(path, HTTP_HOST='marcos.localhost').status_code, 404)

    def test_root_has_no_tenant_and_no_registration(self):
        response = self.client.get('/', HTTP_HOST='localhost')
        self.assertIsNone(response.wsgi_request.tenant)
        for path in ['/cadastro/', '/conta/']:
            self.assertEqual(self.client.get(path, HTTP_HOST='localhost').status_code, 404)

    def test_localhost_with_port_is_valid_root_host_when_base_domain_is_production(self):
        with self.settings(TENANT_BASE_DOMAIN='tacombinado.net'):
            response = self.client.get('/login/', HTTP_HOST='localhost:8001')
            submitted = self.client.post('/login/', {'email': 'nao-existe@example.test', 'password': 'invalid'}, HTTP_HOST='localhost:8001')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.wsgi_request.tenant)
        self.assertEqual(submitted.status_code, 200)

    def test_registration_uses_host_and_ignores_privilege_injection(self):
        for tenant in [self.marcos, self.wanessa]:
            email = f'{tenant.subdomain}@example.com'
            response = self.client.post('/cadastro/', {
                'email': email.upper(), 'whatsapp': '(11) 99999-1234', 'password1': PASSWORD, 'password2': PASSWORD,
                'tenant_id': self.sofia.pk, 'tenant': self.sofia.pk,
                'tipo': 'ADMIN', 'is_staff': True, 'is_superuser': True,
            }, HTTP_HOST=f'{tenant.subdomain}.localhost')
            self.assertRedirects(response, '/login/', fetch_redirect_response=False)
            user = User.objects.get(email=email)
            self.assertEqual(user.tenant, tenant)
            self.assertEqual(user.tipo, User.Tipo.CLIENTE)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
            self.assertNotEqual(user.password, PASSWORD)
            self.assertTrue(user.check_password(PASSWORD))
            self.assertNotIn('username', [f.name for f in User._meta.fields])
            page = self.client.get('/cadastro/', HTTP_HOST=f'{tenant.subdomain}.localhost')
            self.assertNotContains(page, 'name="tenant')
            self.assertNotContains(page, 'name="username"')

    def test_password_confirmation_and_validators(self):
        for password1, password2 in [(PASSWORD, 'different'), ('12345678', '12345678')]:
            response = self.client.post('/cadastro/', {'email': 'new@example.com', 'whatsapp': '11999991234', 'password1': password1, 'password2': password2}, HTTP_HOST='marcos.localhost')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_email_login_without_username_and_logout(self):
        response = self.post_login(email='CLIENTE@EXEMPLO.COM')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        page = self.client.get('/conta/', HTTP_HOST='marcos.localhost')
        self.assertContains(page, self.user.email)
        self.assertEqual(self.client.get('/logout/', HTTP_HOST='marcos.localhost').status_code, 405)
        response = self.client.post('/logout/', HTTP_HOST='marcos.localhost')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/conta/', HTTP_HOST='marcos.localhost').status_code, 302)

    def test_wrong_password_and_wrong_tenant_do_not_create_session(self):
        for host, extra in [('marcos.localhost', {'password': 'wrong'}), ('wanessa.localhost', {})]:
            response = self.post_login(host, **extra)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('_auth_user_id', self.client.session)
            self.assertTrue(response.context['form'].errors)

    def test_copied_session_is_rejected_on_other_tenants_and_root(self):
        self.post_login()
        for host in ['wanessa.localhost', 'sofia.localhost', 'localhost']:
            for path in ['/', '/conta/', '/cadastro/', '/login/']:
                response = self.client.get(path, HTTP_HOST=host)
                self.assertEqual(response.status_code, 403)
                self.assertNotContains(response, self.user.email, status_code=403)
        self.user.tenant = self.wanessa
        self.user.save()
        self.assertEqual(self.client.get('/conta/', HTTP_HOST='sofia.localhost').status_code, 403)
        self.assertEqual(self.client.get('/conta/', HTTP_HOST='marcos.localhost').status_code, 403)

    def test_inactive_user_login_and_existing_session(self):
        self.post_login()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.client.get('/conta/', HTTP_HOST='marcos.localhost').status_code, 302)
        self.client.logout()
        self.assertEqual(self.post_login().status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_disabled_tenant_invalidates_existing_access(self):
        self.post_login()
        Tenant.objects.filter(pk=self.marcos.pk).update(ativo=False)
        self.assertEqual(self.client.get('/conta/', HTTP_HOST='marcos.localhost').status_code, 404)
        self.assertEqual(self.post_login().status_code, 404)

    def test_duplicate_email_rejected_across_tenants_form_and_database(self):
        response = self.client.post('/cadastro/', {'email': self.user.email.upper(), 'whatsapp': '11999991234', 'password1': PASSWORD, 'password2': PASSWORD}, HTTP_HOST='wanessa.localhost')
        self.assertIn('email', response.context['form'].errors)
        for email in [self.user.email, self.user.email.upper()]:
            with self.subTest(email=email), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.bulk_create([User(email=email, tenant=self.wanessa, password='!')])

    def test_database_requires_tenant_normalized_email_and_valid_tipo(self):
        for fields in [dict(email='orphan@example.com'), dict(email='Mixed@example.com', tenant=self.marcos), dict(email='space@example.com ', tenant=self.marcos), dict(email='type@example.com', tenant=self.marcos, tipo='INVALID'), dict(email='', tenant=self.marcos)]:
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.bulk_create([User(password='!', **fields)])
        with self.assertRaises(ValidationError):
            User.objects.create_user('orphan@example.com', PASSWORD)

    def test_client_relationship_cannot_cross_tenants_even_via_bulk_write(self):
        cliente = Cliente(nome='Legado', telefone='11999999999', user=self.user, tenant=self.wanessa)
        with self.assertRaises(ValidationError):
            cliente.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cliente.objects.bulk_create([cliente])
        cliente.tenant = self.marcos
        cliente.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.user.pk).update(tenant=self.wanessa)

    def test_global_superuser_only_on_root_admin(self):
        admin = User.objects.create_superuser('admin@example.com', PASSWORD)
        response = self.client.post('/admin/login/?next=/admin/', {'username': admin.email, 'password': PASSWORD, 'next': '/admin/'}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/admin/', HTTP_HOST='localhost').status_code, 200)
        self.assertEqual(self.client.get('/conta/', HTTP_HOST='marcos.localhost').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/admin/login/', HTTP_HOST='marcos.localhost').status_code, 404)
        self.assertEqual(self.post_login(email=admin.email).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_backend_fails_without_tenant_resolution(self):
        self.assertIsNone(authenticate(email=self.user.email, password=PASSWORD))
        request = RequestFactory().get('/')
        self.assertIsNone(authenticate(request, email=self.user.email, password=PASSWORD))

    def test_csrf_required_and_cookies_are_host_only(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/cadastro/', {}, HTTP_HOST='marcos.localhost').status_code, 403)
        self.assertEqual(client.post('/login/', {}, HTTP_HOST='marcos.localhost').status_code, 403)
        self.post_login()
        self.assertEqual(self.client.cookies['sessionid']['domain'], '')
        client.cookies = self.client.cookies
        self.assertEqual(client.post('/logout/', HTTP_HOST='marcos.localhost').status_code, 403)


    def test_global_admin_can_edit_only_tenant_user_role(self):
        admin = User.objects.create_superuser('global@example.com', PASSWORD)
        self.client.force_login(admin)
        url = reverse('admin:usuarios_user_change', args=[self.user.pk])
        page = self.client.get(url, HTTP_HOST='localhost')
        self.assertContains(page, 'name="tipo"')
        self.assertNotContains(page, 'name="tenant"')
        response = self.client.post(url, {
            'tipo': 'ADMIN', 'tenant': self.wanessa.pk,
            'is_staff': 'on', 'is_superuser': 'on', '_save': 'Salvar',
        }, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.tipo, 'ADMIN')
        self.assertEqual(self.user.tenant, self.marcos)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='marcos.localhost').status_code, 200)
        self.assertEqual(self.client.post(url, {'tipo': 'CLIENTE'}, HTTP_HOST='localhost').status_code, 403)

    def test_global_superuser_role_is_readonly(self):
        admin = User.objects.create_superuser('global@example.com', PASSWORD)
        self.client.force_login(admin)
        url = reverse('admin:usuarios_user_change', args=[admin.pk])
        page = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="tipo"')
        self.assertEqual(self.client.post(url, {'tipo': 'CLIENTE'}, HTTP_HOST='localhost').status_code, 403)
