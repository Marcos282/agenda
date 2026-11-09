from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright


@override_settings(
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='',
)
class PrivacyBrowserTests(StaticLiveServerTestCase):
    def test_policy_is_readable_without_overflow_at_mobile_and_desktop_sizes(self):
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
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for root in (
                self.live_server_url,
                self.live_server_url.replace('localhost', 'inexistente.localhost'),
            ):
                response = page.goto(root + '/politica-de-privacidade/')
                self.assertEqual(response.status, 200)
                expect(page.get_by_role('heading', name='Política de Privacidade', exact=True)).to_be_visible()
                expect(page.locator('article section')).to_have_count(10)
                expect(page.locator('script, iframe, form')).to_have_count(0)
                expect(page.locator('footer .privacy-link')).to_have_attribute(
                    'href', 'https://tacombinado.net/politica-de-privacidade/',
                )
                expect(page.locator('footer a[href^="mailto:"]')).to_have_attribute(
                    'href', 'mailto:contato@novarede.net.br',
                )
                cloudflare_link = page.locator('#turnstile a')
                expect(cloudflare_link).to_have_attribute('target', '_blank')
                expect(cloudflare_link).to_have_attribute('rel', 'noopener noreferrer')
                for width in (1440, 768, 390, 320):
                    with self.subTest(root=root, width=width):
                        page.set_viewport_size({'width': width, 'height': 900})
                        self.assertLessEqual(
                            page.evaluate('document.documentElement.scrollWidth'), width,
                        )
                        for selector in ('article', 'h1', '.privacy-summary', '#turnstile a', 'footer'):
                            element = page.locator(selector)
                            box = element.bounding_box()
                            self.assertIsNotNone(box)
                            self.assertGreaterEqual(box['x'], 0)
                            self.assertLessEqual(box['x'] + box['width'], width)
                        self.assertGreaterEqual(
                            float(page.locator('article p').first.evaluate(
                                'el => parseFloat(getComputedStyle(el).fontSize)',
                            )),
                            16,
                        )
                        page.get_by_role('link', name='Contato e atualização', exact=True).click()
                        expect(page.locator('#contato h2')).to_be_in_viewport()
            self.assertEqual(errors, [])
            browser.close()
