from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from tenants.models import Tenant
from usuarios.models import User


@override_settings(
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='', PLATFORM_MONTHLY_PRICE='30.00',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class SinglePlanBrowserTests(StaticLiveServerTestCase):
    def test_single_plan_on_public_signup_and_panel_at_mobile_and_desktop_sizes(self):
        tenant = Tenant.objects.create(nome='Plano único', subdomain='plano-unico')
        admin = User.objects.create_user('single-plan@example.test', tenant=tenant, tipo='ADMIN')
        self.client.force_login(admin)
        tenant_url = self.live_server_url.replace('localhost', 'plano-unico.localhost')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='/usr/bin/google-chrome', args=['--no-sandbox'],
            )
            context = browser.new_context()

            def local_only(route):
                host = urlsplit(route.request.url).hostname or ''
                if host == 'localhost' or host.endswith('.localhost'):
                    route.continue_()
                else:
                    route.abort()

            context.route('**/*', local_only)
            context.add_cookies([{
                'name': 'sessionid', 'value': self.client.cookies['sessionid'].value,
                'url': tenant_url,
            }])
            page = context.new_page()
            for path, selector, text in [
                (self.live_server_url + '/', '.pricing-card', '30,00'),
                (self.live_server_url + '/registro', 'main', 'R$ 30,00/mês'),
                (tenant_url + '/painel/mensalidade/', '.billing-choice', 'R$ 30,00'),
            ]:
                with self.subTest(path=path):
                    page.goto(path)
                    card = page.locator(selector)
                    expect(card).to_have_count(1)
                    expect(card).to_contain_text('Plano Profissional')
                    expect(card).to_contain_text(text)
                    expect(page.get_by_text('Plano Individual', exact=False)).to_have_count(0)
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 900})
                        expect(card).to_be_visible()
                        self.assertLessEqual(
                            card.evaluate('el => el.getBoundingClientRect().right'), width,
                        )
                        self.assertGreaterEqual(
                            card.evaluate('el => el.getBoundingClientRect().left'), 0,
                        )
                        self.assertLessEqual(
                            card.evaluate('el => el.scrollWidth'),
                            card.evaluate('el => el.clientWidth'),
                        )
            expect(page.get_by_role('button', name='Renovar por 30 dias')).to_have_count(1)
            expect(page.locator('input[name="plano"]')).to_have_value('PROFISSIONAL')
            browser.close()
