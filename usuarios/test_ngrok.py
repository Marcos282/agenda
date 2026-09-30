from django.test import Client, TestCase, override_settings
from tenants.models import Tenant
from usuarios.models import User


@override_settings(
    DEBUG=True, TENANT_BASE_DOMAIN='localhost', DEV_PUBLIC_HOST='checkout.ngrok-free.dev',
    DEV_TENANT_SUBDOMAIN='marcos', ALLOWED_HOSTS=['checkout.ngrok-free.dev', '.localhost', 'localhost'],
    CSRF_TRUSTED_ORIGINS=['https://checkout.ngrok-free.dev'],
)
class NgrokRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marcos = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        cls.owner = User.objects.create_user('marcos@example.test', 'Original!2026Password', tenant=cls.marcos, tipo='ADMIN')

    def test_registration_login_and_panel_use_same_tunnel(self):
        host = {'HTTP_HOST': 'checkout.ngrok-free.dev'}
        self.assertContains(self.client.get('/registro', **host), 'Criar meu estabelecimento')
        self.assertContains(self.client.get('/registro/', **host), 'Criar meu estabelecimento')
        response = self.client.post('/registro', {
            'subdomain': 'novo', 'email': 'novo@example.test',
            'password1': 'Nova!Senha2026Segura', 'password2': 'Nova!Senha2026Segura',
        }, **host)
        self.assertEqual(response.url, '/registro/concluido/')
        self.assertContains(self.client.get(response.url, **host), 'Cadastro concluído!')
        response = self.client.post('/login/', {'email': 'novo@example.test', 'password': 'Nova!Senha2026Segura'}, **host)
        self.assertEqual(response.url, '/painel/')
        page = self.client.get('/painel/mensalidade/', **host)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.wsgi_request.tenant.subdomain, 'novo')
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='marcos.localhost').status_code, 403)

    def test_anonymous_store_stays_marcos_and_existing_owner_can_open_registration(self):
        host = {'HTTP_HOST': 'checkout.ngrok-free.dev'}
        self.assertEqual(self.client.get('/', **host).wsgi_request.tenant, self.marcos)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get('/registro', **host), 'Criar meu estabelecimento')
        self.assertEqual(self.client.get('/painel/', **host).wsgi_request.tenant, self.marcos)

    def test_tenant_domains_and_production_do_not_allow_registration(self):
        self.assertEqual(self.client.get('/registro', HTTP_HOST='marcos.localhost').status_code, 404)
        with self.settings(DEBUG=False):
            self.assertEqual(self.client.get('/registro', HTTP_HOST='checkout.ngrok-free.dev').status_code, 404)

    def test_wrong_password_and_csrf_cannot_start_session(self):
        host = {'HTTP_HOST': 'checkout.ngrok-free.dev'}
        response = self.client.post('/login/', {'email': self.owner.email, 'password': 'invalid'}, **host)
        self.assertContains(response, 'E-mail ou senha inválidos')
        self.assertNotIn('_auth_user_id', self.client.session)
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post('/registro', {}, **host).status_code, 403)
