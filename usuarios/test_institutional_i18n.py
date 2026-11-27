from unittest.mock import Mock, patch

from django.conf import settings
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.utils.translation import get_language, override

from .institutional_i18n import LANGUAGES, PAGES, InstitutionalLocaleMiddleware, localized_path


@override_settings(
    DEBUG=False, TENANT_BASE_DOMAIN='tacombinado.net',
    ALLOWED_HOSTS=['.tacombinado.net'], PLATFORM_PUBLIC_URL='https://tacombinado.net/',
)
class InstitutionalTranslationTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(
            enforce_csrf_checks=True, HTTP_HOST='tacombinado.net',
            HTTP_ORIGIN='https://tacombinado.net',
        )

    def test_browser_language_and_explicit_portuguese(self):
        first = self.client.get('/?ref=campaign', HTTP_ACCEPT_LANGUAGE='fr-CA,en;q=0.8', secure=True)
        self.assertRedirects(first, '/fr/?ref=campaign', fetch_redirect_response=False)
        self.assertIn('Accept-Language', first['Vary'])
        self.assertIn('Cookie', first['Vary'])
        response = self.client.get('/fr/', secure=True)
        self.assertContains(response, 'Se connecter')
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        switch = self.client.post('/idioma/', {
            'page': 'home', 'language': 'pt-br', 'csrfmiddlewaretoken': token,
        }, secure=True)
        self.assertRedirects(switch, '/', fetch_redirect_response=False)
        cookie = switch.cookies[settings.LANGUAGE_COOKIE_NAME]
        self.assertEqual(cookie.value, 'pt-br')
        self.assertTrue(cookie['secure'] and cookie['httponly'])
        portuguese = self.client.get('/', HTTP_ACCEPT_LANGUAGE='fr', secure=True)
        self.assertContains(portuguese, 'Como usar')
        self.assertEqual(portuguese['Content-Language'], 'pt-br')

    def test_metadata_and_explicit_language_for_every_marketing_page(self):
        for name in PAGES:
            descriptions = set()
            for code, tag, _, _, _ in LANGUAGES:
                with self.subTest(page=name, language=code):
                    path = localized_path(name, code)
                    response = self.client.get(path, secure=True)
                    self.assertContains(response, f'<html lang="{tag}">')
                    self.assertEqual(response['Content-Language'], code)
                    self.assertContains(response, f'rel="canonical" href="https://tacombinado.net{path}"')
                    self.assertContains(response, 'rel="alternate" hreflang=', count=7)
                    descriptions.add(str(response.context['seo_description']))
            self.assertEqual(len(descriptions), 6)

    def test_language_selection_requires_csrf_and_valid_destination(self):
        self.assertEqual(self.client.post('/idioma/', {'page': 'home', 'language': 'de'}, secure=True).status_code, 403)
        self.client.get('/', secure=True)
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post('/idioma/', {
            'page': '//example.com', 'language': 'de', 'csrfmiddlewaretoken': token,
        }, secure=True)
        self.assertEqual(response.status_code, 404)

    def test_prefixed_pages_and_cookie_do_not_apply_to_tenant(self):
        tenant = Mock(agendamentos_bloqueados=False, timezone='America/Sao_Paulo')
        with (patch('tenants.middleware.resolve_tenant', return_value=tenant),
              patch('tenants.theme_context.TenantTheme.objects.filter') as theme_filter):
            theme_filter.return_value.first.return_value = None
            response = self.client.get('/de/', HTTP_HOST='loja.tacombinado.net', secure=True)
            self.assertEqual(response.status_code, 404)
            response = self.client.get('/admin/', HTTP_HOST='loja.tacombinado.net', secure=True)
            self.assertEqual(response.status_code, 404)

        middleware = InstitutionalLocaleMiddleware(lambda request: HttpResponse(get_language()))
        for path, site_tenant in (('/', tenant), ('/login/', None), ('/admin/', None), ('/agendamentos/', tenant)):
            with self.subTest(path=path):
                request = RequestFactory().get(path, HTTP_HOST='tacombinado.net', HTTP_ACCEPT_LANGUAGE='de')
                request.tenant = site_tenant
                request.COOKIES[settings.LANGUAGE_COOKIE_NAME] = 'de'
                with override('pt-br'):
                    self.assertContains(middleware(request), 'pt-br')

    def test_store_lookup_validation_is_translated(self):
        response = self.client.get('/de/', {'estabelecimento': 'invalid address'}, secure=True)
        self.assertContains(response, 'Verwenden Sie eine Subdomain')
