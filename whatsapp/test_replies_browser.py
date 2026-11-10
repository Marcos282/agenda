from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from usuarios.models import User
from .test_replies import ReplyFixture
from .reply_views import webhook_token


@override_settings(DEBUG=True, SESSION_COOKIE_SECURE=False,
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='', EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class ReplyBrowserTests(ReplyFixture, StaticLiveServerTestCase):
    def test_reply_updates_real_agenda_and_customer_history(self):
        with patch('whatsapp.services.enviar_confirmacao_agendamento'):
            self.setup_replies()
        admin = User.objects.create_user('browser-replies@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        root = self.live_server_url.replace('localhost', 'marcos.localhost')
        url = root + reverse('painel:agenda') + f'?profissional={self.prof.pk}&data={self.day.isoformat()}'
        with patch('whatsapp.evolution.send_text', return_value={'message_id': 'ack'}), sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                'domain': 'marcos.localhost', 'path': '/'}])
            context.route('**/*', lambda route: route.continue_()
                if (urlsplit(route.request.url).hostname or '').endswith('.localhost') else route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            self.assertEqual(page.goto(url).status, 200)
            expect(page.get_by_text('🟡 Aguardando confirmação', exact=True)).to_be_visible()
            with patch('whatsapp.replies.timezone.now', return_value=self.now):
                response = context.request.post(root + reverse('whatsapp_appointment_reply'),
                    data=self.payload(), headers={'X-Agendamento-Token': webhook_token(self.tenant)})
            self.assertEqual(response.status, 200)
            page.reload()
            expect(page.get_by_text('🟢 Confirmado pelo cliente', exact=True)).to_be_visible()
            with patch('whatsapp.replies.timezone.now', return_value=self.now):
                response = context.request.post(root + reverse('whatsapp_appointment_reply'),
                    data=self.payload('2', 'cancel'), headers={'X-Agendamento-Token': webhook_token(self.tenant)})
            self.assertEqual(response.status, 200)
            page.reload()
            expect(page.locator('.timeline-block.booked')).to_have_count(0)
            page.goto(root + reverse('painel:whatsapp_historico', args=[self.user.whatsapp]))
            expect(page.get_by_text('🔴 Cancelado pelo cliente', exact=True)).to_be_visible()
            expect(page.get_by_text('Presença confirmada em', exact=False)).to_be_visible()
            self.assertEqual(errors, [])
            browser.close()
