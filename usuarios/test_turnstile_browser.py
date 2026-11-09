from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import sync_playwright

from agenda.models import Agendamento
from agenda.test_booking import BookingFixture
from .test_turnstile import (
    KEYS, SITEVERIFY, TEST_AUTH_SITE_KEY, TEST_PUBLIC_SITE_KEY,
    TEST_RESPONSE, TEST_SECRET_KEY, TEST_TOKEN,
)


@override_settings(**{
    **KEYS,
    'DEBUG': True,
    'DEV_PUBLIC_HOST': '',
    'DEV_TENANT_SUBDOMAIN': '',
    'TURNSTILE_PUBLIC_SITE_KEY': TEST_PUBLIC_SITE_KEY,
    'TURNSTILE_PUBLIC_SECRET_KEY': TEST_SECRET_KEY,
    'TURNSTILE_AUTH_SITE_KEY': TEST_AUTH_SITE_KEY,
    'TURNSTILE_AUTH_SECRET_KEY': TEST_SECRET_KEY,
})
class LocalTurnstileBrowserTests(BookingFixture, StaticLiveServerTestCase):
    def setUp(self):
        super().setUp()
        self.setup_booking()

    def test_mobile_booking_can_be_confirmed_twice_with_dummy_token(self):
        script = """
            (() => {
                let box, options;
                window.turnstile = {
                    render(element, config) {
                        box = element;
                        options = config;
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = config['response-field-name'];
                        box.appendChild(input);
                        return 'test-widget';
                    },
                    reset() { box.querySelector('input').value = ''; },
                    execute() {
                        box.querySelector('input').value = '%s';
                        setTimeout(() => options.callback(), 0);
                    }
                };
                window.tcTurnstilePublicReady();
            })();
        """ % TEST_TOKEN
        url = self.live_server_url.replace('localhost', 'marcos.localhost') + self.slots_url()
        with patch(SITEVERIFY, return_value=TEST_RESPONSE) as siteverify, sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='/usr/bin/google-chrome', args=['--no-sandbox'],
            )
            context = browser.new_context(viewport={'width': 390, 'height': 844})

            def route_request(route):
                url_parts = urlsplit(route.request.url)
                if url_parts.hostname == 'challenges.cloudflare.com' and url_parts.path.endswith('/turnstile/v0/api.js'):
                    route.fulfill(status=200, content_type='application/javascript', body=script)
                elif url_parts.hostname == 'localhost' or (url_parts.hostname or '').endswith('.localhost'):
                    route.continue_()
                else:
                    route.abort()

            context.route('**/*', route_request)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for hour, phone in (('09:07', '(11) 99999-1234'), ('09:47', '(11) 99999-5678')):
                with self.subTest(hour=hour):
                    response = page.goto(url)
                    self.assertEqual(response.status, 200)
                    page.locator(f'input[name="hora"][value="{hour}"]').check()
                    page.locator('input[name="nome"]').fill('Cliente Teste')
                    page.locator('input[name="whatsapp"]').fill(phone)
                    page.get_by_role('button', name='Confirmar agendamento').click()
                    page.wait_for_url('**/agendamentos/acompanhar/**')
            self.assertEqual(errors, [])
            self.assertEqual(siteverify.call_count, 2)
            browser.close()
        self.assertEqual(Agendamento.objects.filter(tenant=self.tenant).count(), 2)
