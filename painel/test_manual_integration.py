from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from tenants.models import Tenant
from usuarios.models import User


@override_settings(
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class ManualIntegrationTests(StaticLiveServerTestCase):
    def test_manual_links_and_onboarding_across_hosts_and_viewports(self):
        now = timezone.now()
        panel_path = reverse('painel:inicio')
        manual_path = reverse('manual')
        manual_destination = manual_path + '#primeiros-passos'
        manual_origin = 'https://tacombinado.net'
        manual_url = manual_origin + manual_destination
        panel_sessions = []
        for subdomain, age in [('novo', 6), ('antigo', 8)]:
            tenant = Tenant.objects.create(nome=subdomain, subdomain=subdomain)
            Tenant.objects.filter(pk=tenant.pk).update(criado_em=now - timedelta(days=age))
            admin = User.objects.create_user(f'{subdomain}@example.test', tenant=tenant, tipo='ADMIN')
            client = Client()
            client.force_login(admin)
            tenant_host = f'{subdomain}.localhost'
            panel_sessions.append((
                self.live_server_url.replace('localhost', tenant_host),
                client.cookies['sessionid'].value,
                age < 7,
            ))
            if age < 7:
                with patch('painel.views.timezone.now', return_value=now + timedelta(days=1)):
                    response = client.get(panel_path, HTTP_HOST=tenant_host)
                self.assertNotContains(response, 'Assistir aos tutoriais')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            context = browser.new_context()

            def route_request(route):
                host = urlsplit(route.request.url).hostname
                if route.request.url.split('#', 1)[0] == manual_origin + manual_path:
                    route.fulfill(status=200, content_type='text/plain', body='Manual do Sistema')
                elif host == 'localhost' or (host and host.endswith('.localhost')):
                    route.continue_()
                else:
                    route.abort()

            context.route('**/*', route_request)
            for tenant_url, session, _ in panel_sessions:
                context.add_cookies([{'name': 'sessionid', 'value': session, 'url': tenant_url}])
            page = context.new_page()
            for width in (1280, 768, 390, 320):
                with self.subTest(width=width):
                    page.set_viewport_size({'width': width, 'height': 900})
                    for label, region in [('Como usar', 'header nav'), ('Manual do Sistema', 'footer')]:
                        self.assertEqual(page.goto(self.live_server_url).status, 200)
                        link = page.locator(region).get_by_role('link', name=label, exact=True)
                        expect(link).to_be_visible()
                        self.assertLessEqual(link.bounding_box()['x'] + link.bounding_box()['width'], width)
                        link.click()
                        expect(page).to_have_url(self.live_server_url + manual_destination)
                        expect(page.locator('#primeiros-passos [data-video-player]')).to_be_in_viewport()
                        expect(page.locator('#primeiros-passos [data-tutorial]').first).to_have_attribute('open', '')

                    for tenant_url, _, show_card in panel_sessions:
                        self.assertEqual(page.goto(tenant_url + panel_path).status, 200)
                        help_link = page.get_by_role('navigation', name='Painel administrativo').get_by_role(
                            'link', name='Central de Ajuda', exact=True)
                        expect(help_link).to_have_attribute('rel', 'noopener noreferrer')
                        expect(help_link).to_have_attribute('target', '_blank')
                        with context.expect_page() as new_page:
                            help_link.click()
                        expect(new_page.value).to_have_url(manual_url)
                        new_page.value.close()
                        expect(page).to_have_url(tenant_url + panel_path)
                        tutorials = page.get_by_role('link', name='Assistir aos tutoriais', exact=True)
                        if show_card:
                            expect(tutorials).to_be_visible()
                            self.assertLessEqual(tutorials.bounding_box()['x'] + tutorials.bounding_box()['width'], width)
                            tutorials.click()
                            expect(page).to_have_url(manual_url)
                        else:
                            expect(tutorials).to_have_count(0)
            browser.close()
