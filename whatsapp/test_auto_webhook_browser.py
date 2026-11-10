from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from tenants.models import Tenant
from usuarios.models import User
from . import evolution
from .reply_views import webhook_token


@override_settings(DEBUG=True, SESSION_COOKIE_SECURE=False, TENANT_BASE_DOMAIN='localhost',
    STORE_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='', EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class AutoWebhookBrowserTests(StaticLiveServerTestCase):
    def test_connection_failure_retry_and_idempotent_verification(self):
        tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        admin = User.objects.create_user('auto-browser@example.test', tenant=tenant, tipo='ADMIN')
        self.client.force_login(admin)
        root = self.live_server_url.replace('localhost', 'marcos.localhost')
        ready = {'enabled': True, 'url': 'https://marcos.localhost/whatsapp/respostas/',
                 'events': ['MESSAGES_UPSERT'], 'headers': {'X-Agendamento-Token': webhook_token(tenant)}}
        with patch('whatsapp.evolution.configured', return_value=True), \
                patch('whatsapp.evolution.connection_info', return_value={'state': 'open', 'number': ''}), \
                patch('whatsapp.evolution.connect', return_value=''), \
                patch('whatsapp.evolution.request', side_effect=[evolution.EvolutionError('private'), None, {}, ready, ready]) as api, \
                sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                'domain': 'marcos.localhost', 'path': '/'}])
            context.route('**/*', lambda route: route.continue_()
                if (urlsplit(route.request.url).hostname or '').endswith('.localhost') else route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            self.assertEqual(page.goto(root + reverse('painel:whatsapp')).status, 200)
            self.assertEqual(api.call_count, 0)
            page.get_by_role('button', name='Conectar / gerar QR code', exact=True).click()
            retry = page.get_by_role('button', name='Tentar configurar recebimento novamente', exact=True)
            expect(retry).to_be_visible()
            self.assertNotIn('private', page.content())
            retry.click()
            expect(page.get_by_text('Recebimento de respostas configurado.', exact=True)).to_be_visible()
            expect(retry).to_have_count(0)
            page.get_by_role('button', name='Verificar conexão', exact=True).click()
            expect(page.get_by_text('Recebimento de respostas configurado.', exact=True)).to_be_visible()
            self.assertEqual(sum(call.args[0] == 'POST' for call in api.call_args_list), 1)
            expect(page.locator('input[name="confirmar_presenca_whatsapp"]')).not_to_be_checked()
            expect(page.locator('input[name="cancelar_whatsapp"]')).not_to_be_checked()
            self.assertNotIn(webhook_token(tenant), page.content())
            self.assertEqual(errors, [])
            browser.close()
