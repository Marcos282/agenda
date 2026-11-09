from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento
from agenda.test_booking import BookingFixture
from catalogo.models import ProfissionalServico, Servico
from profissionais.models import Profissional
from tenants.models import Tenant, TenantTheme
from usuarios.models import User


PRIVACY_URL = 'https://tacombinado.net/politica-de-privacidade/'


@override_settings(
    DEBUG=False,
    TENANT_BASE_DOMAIN='tacombinado.net',
    ALLOWED_HOSTS=['tacombinado.net', '.tacombinado.net'],
    DEV_PUBLIC_HOST='',
    DEV_TENANT_SUBDOMAIN='',
)
class PrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            nome='Estabelecimento confidencial', subdomain='salao',
            expira_em=timezone.localdate() - timedelta(days=1),
        )
        cls.other = Tenant.objects.create(nome='Outro estabelecimento', subdomain='outro')
        cls.inactive = Tenant.objects.create(nome='Loja inativa', subdomain='inativo', ativo=False)
        TenantTheme.objects.create(tenant=cls.tenant, title='Tema confidencial')
        cls.admin = User.objects.create_user(
            'admin-privado@example.test', 'SenhaPrivada!2026',
            tenant=cls.tenant, tipo=User.Tipo.ADMIN, cpf='12345678901',
            endereco='Endereco privado de teste',
        )
        cls.professional = Profissional.objects.create(tenant=cls.other, nome='Profissional teste')
        service = Servico.objects.create(tenant=cls.other, nome='Servico teste')
        cls.offer = ProfissionalServico.objects.create(
            tenant=cls.other, profissional=cls.professional, servico=service,
            valor='40.00', duracao_minutos=40,
        )

    def get_policy(self, host='tacombinado.net'):
        return self.client.get(reverse('politica_privacidade'), HTTP_HOST=host, secure=True)

    def test_public_document_is_identical_on_root_and_subdomains_without_database_queries(self):
        original = self.get_policy().content
        for host in (
            'tacombinado.net', 'salao.tacombinado.net', 'outro.tacombinado.net',
            'inativo.tacombinado.net', 'inexistente.tacombinado.net',
        ):
            with self.subTest(host=host), self.assertNumQueries(0):
                response = self.get_policy(host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, original)
                self.assertIsNone(response.wsgi_request.tenant)
                self.assertNotIn('sessionid', response.cookies)

    def test_authenticated_visitor_can_read_without_changing_session_or_isolation(self):
        self.client.force_login(self.admin)
        session_key = self.client.session.session_key
        for host in ('tacombinado.net', 'salao.tacombinado.net', 'outro.tacombinado.net'):
            with self.subTest(host=host):
                self.assertEqual(self.get_policy(host).status_code, 200)
        self.assertEqual(self.client.session.session_key, session_key)
        for path in ('/', '/login/', '/conta/', '/painel/'):
            for host in ('outro.tacombinado.net', 'tacombinado.net'):
                with self.subTest(host=host, path=path):
                    response = self.client.get(path, HTTP_HOST=host, secure=True)
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.get('/conta/', HTTP_HOST='salao.tacombinado.net', secure=True).status_code,
            200,
        )

    def test_host_validation_and_non_policy_routes_are_unchanged(self):
        self.assertEqual(self.get_policy('untrusted.example').status_code, 400)
        for host in ('inativo.tacombinado.net', 'inexistente.tacombinado.net'):
            response = self.client.get('/', HTTP_HOST=host, secure=True)
            self.assertEqual(response.status_code, 404)

    @override_settings(
        DEBUG=True, DEV_PUBLIC_HOST='tunnel.example.test', DEV_TENANT_SUBDOMAIN='missing',
        ALLOWED_HOSTS=['tunnel.example.test'],
    )
    def test_development_tunnel_does_not_require_a_configured_tenant(self):
        self.assertEqual(self.get_policy('tunnel.example.test').status_code, 200)

    def test_document_contains_required_sections_and_no_sensitive_context_or_scripts(self):
        response = self.get_policy('salao.tacombinado.net')
        self.assertTemplateUsed(response, 'usuarios/plataforma.html')
        self.assertContains(response, '<section id=', count=10)
        self.assertContains(response, '<time datetime="2026-11-09">')
        self.assertContains(response, 'contato@novarede.net.br')
        self.assertContains(response, 'CNPJ 48.992.693/0001-72')
        self.assertContains(response, 'na confirmação de agendamentos públicos, de forma invisível')
        self.assertContains(response, 'O Tá Combinado utiliza o Cloudflare Turnstile')
        self.assertContains(
            response,
            '<a href="https://www.cloudflare.com/en-gb/turnstile-privacy-policy/" '
            'target="_blank" rel="noopener noreferrer">'
            'https://www.cloudflare.com/en-gb/turnstile-privacy-policy/</a>',
            html=True,
        )
        self.assertContains(response, '<link rel="canonical" href="' + PRIVACY_URL + '">', html=True)
        for value in (
            self.admin.email, self.admin.password, self.admin.cpf, self.admin.endereco,
            self.tenant.nome, 'Tema confidencial', '<script', '<form',
            'challenges.cloudflare.com', 'googletagmanager.com', 'sitekey',
        ):
            with self.subTest(value=value):
                self.assertNotContains(response, value)

    def test_footer_links_are_canonical_and_not_duplicated(self):
        for host, path in (
            ('tacombinado.net', '/'),
            ('tacombinado.net', '/login/'),
            ('tacombinado.net', '/registro'),
            ('tacombinado.net', reverse('politica_privacidade')),
            ('outro.tacombinado.net', '/'),
            ('outro.tacombinado.net', '/login/'),
            ('outro.tacombinado.net', f'/profissional/{self.professional.pk}/'),
            ('outro.tacombinado.net', f'/loja/{self.offer.pk}/'),
            ('salao.tacombinado.net', '/agendamentos/servico/1/'),
        ):
            with self.subTest(host=host, path=path):
                response = self.client.get(path, HTTP_HOST=host, secure=True)
                self.assertIn(response.status_code, (200, 503))
                footer = response.content.decode().split('<footer', 1)[1].split('</footer>', 1)[0]
                self.assertIn('href="' + PRIVACY_URL + '"', footer)
                self.assertContains(response, 'class="privacy-link"', count=1, status_code=response.status_code)

    def test_policy_does_not_resolve_any_tenant(self):
        with patch('tenants.middleware.resolve_tenant') as resolve:
            response = self.get_policy()
        self.assertEqual(response.status_code, 200)
        resolve.assert_not_called()


@override_settings(
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='',
)
class PrivacyBookingTests(BookingFixture, TestCase):
    def test_guest_can_read_policy_between_booking_steps_without_losing_access(self):
        self.setup_booking()
        host = {'HTTP_HOST': 'marcos.localhost'}
        self.assertContains(self.client.get(self.slots_url(), **host), 'name="whatsapp"')
        self.assertEqual(
            self.client.get(reverse('politica_privacidade'), **host).status_code, 200,
        )
        response = self.client.post(self.slots_url(), self.payload(), **host)
        self.assertEqual(response.status_code, 302)
        booking = Agendamento.objects.get()
        self.assertEqual(booking.tenant_id, self.tenant.pk)
        self.assertIsNone(booking.cliente_id)
        session_key = self.client.session.session_key
        self.assertEqual(
            self.client.get(reverse('politica_privacidade'), HTTP_HOST='localhost').status_code,
            200,
        )
        self.assertEqual(self.client.session.session_key, session_key)
        self.assertContains(self.client.get(response.url, **host), 'Confirmado')
        self.assertEqual(
            self.client.get(response.url, HTTP_HOST='wanessa.localhost').status_code, 404,
        )
        self.assertEqual(self.client.post(response.url, **host).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CANCELADO')
