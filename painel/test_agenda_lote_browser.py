from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import sync_playwright, expect

from agenda.models import Disponibilidade
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User


@override_settings(DEBUG=True, TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='', SESSION_COOKIE_SECURE=False,
    EVOLUTION_API_URL='', EVOLUTION_API_KEY='')
class BatchAgendaBrowserTests(StaticLiveServerTestCase):
    def test_dates_shortcuts_responsiveness_and_confirmation(self):
        tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        prof = Profissional.objects.create(tenant=tenant, nome='Ana Silva')
        Profissional.objects.create(tenant=tenant, nome='Bia Santos')
        Profissional.objects.create(tenant=tenant, nome='Profissional inativo', ativo=False)
        admin = User.objects.create_user('batch-browser@example.test', tenant=tenant, tipo='ADMIN')
        self.client.force_login(admin)
        root = self.live_server_url.replace('localhost', 'marcos.localhost')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                'domain': 'marcos.localhost', 'path': '/'}])
            context.route('**/*', lambda route: route.continue_()
                if (urlsplit(route.request.url).hostname or '').endswith('.localhost') else route.abort())
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            self.assertEqual(page.goto(root + reverse('painel:agenda')).status, 200)
            page.get_by_role('link', name='Abrir agendas em lote', exact=True).click()
            expect(page.locator('[name="quantidade_dias"]')).to_have_value('7')
            expect(page.locator('[name="datas"]')).to_have_count(7)
            expect(page.locator('[name="profissionais"]')).to_have_count(2)
            page.get_by_role('button', name='Selecionar todos os profissionais', exact=True).click()
            page.get_by_role('button', name='Segunda a sexta', exact=True).click()
            self.assertEqual(page.locator('[name="datas"]:checked').count(), 5)
            page.get_by_role('button', name='Segunda a sábado', exact=True).click()
            self.assertEqual(page.locator('[name="datas"]:checked').count(), 6)
            page.get_by_role('button', name='Limpar seleção', exact=True).click()
            self.assertEqual(page.locator('[name="datas"]:checked').count(), 0)
            page.get_by_role('button', name='Selecionar todos', exact=True).click()
            page.screenshot(path='/tmp/agenda-lote-desktop.png', full_page=True)
            for width in (768, 390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                bar = page.locator('.batch-bar').bounding_box()
                self.assertLessEqual(bar['x'] + bar['width'], width)
            page.screenshot(path='/tmp/agenda-lote-mobile.png', full_page=True)
            # Scoped colors follow inherited variables without changing the global theme.
            page.locator('.batch-page').evaluate("el => el.style.setProperty('--surface', '#182024')")
            self.assertEqual(page.locator('.batch-card').first.evaluate('el => getComputedStyle(el).backgroundColor'), 'rgb(24, 32, 36)')
            page.locator('.batch-page').evaluate("el => el.style.removeProperty('--surface')")
            start = (timezone.localdate() + timedelta(days=3)).isoformat()
            page.locator('[name="data_inicial"]').fill('/'.join(reversed(start.split('-'))))
            page.locator('[name="quantidade_dias"]').fill('1')
            expect(page.locator('[name="datas"]')).to_have_count(1)
            expect(page.locator('[name="datas"]')).to_have_value(start)
            expect(page.locator('.day-choice strong')).to_have_text('/'.join(reversed(start.split('-'))))
            page.locator('[name="profissionais"]').last.uncheck()
            page.get_by_role('button', name='Confirmar abertura das agendas', exact=True).click()
            expect(page.locator('#batch-confirm')).to_be_visible()
            page.get_by_role('button', name='Confirmar abertura', exact=True).click()
            expect(page.locator('#batch-status')).to_contain_text('Agendas configuradas')
            page.locator('[name="manha_inicio"]').fill('09:00')
            page.get_by_role('button', name='Confirmar abertura das agendas', exact=True).click()
            expect(page.locator('#batch-confirm')).to_be_visible()
            expect(page.locator('#batch-confirm-submit')).to_be_disabled()
            page.locator('#batch-overwrite').check()
            page.get_by_role('button', name='Confirmar abertura', exact=True).click()
            expect(page.locator('#batch-status')).to_contain_text('1 atualizadas')
            page.get_by_role('button', name='Confirmar abertura das agendas', exact=True).click()
            expect(page.locator('#batch-confirm')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('#batch-form')).not_to_have_attribute('aria-busy', 'true')
            page.get_by_role('link', name='Conferir agenda configurada', exact=True).click()
            expect(page.locator('#professional-heading')).to_have_text('Ana Silva')
            expect(page.locator('#agenda-date')).to_have_value(start)
            page.goto(root + reverse('painel:agendamento_novo') + f'?profissional={prof.pk}&data={start}')
            trigger = page.get_by_role('button', name='Escolher data no calendário')
            trigger.click()
            popup = page.get_by_role('dialog', name='Escolher data do atendimento')
            expect(popup).to_be_visible()
            popup_box, trigger_box = popup.bounding_box(), trigger.bounding_box()
            self.assertLessEqual(popup_box['y'] + popup_box['height'], trigger_box['y'] - 7)
            self.assertGreaterEqual(popup_box['y'], 0)
            page.screenshot(path='/tmp/calendario-acima-botao.png')
            page.keyboard.press('Escape')
            self.assertEqual(errors, [])
            browser.close()
        self.assertEqual(Disponibilidade.objects.filter(ativo=True, profissional=prof).count(), 2)
        self.assertEqual(Disponibilidade.objects.filter(ativo=True, profissional=prof).first().hora_inicio.strftime('%H:%M'), '09:00')
