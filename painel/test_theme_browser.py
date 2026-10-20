"""Real-browser coverage using a disposable PostgreSQL database."""
from pathlib import Path
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import sync_playwright, expect
from tenants.models import Tenant, TenantTheme
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost'], DEV_PUBLIC_HOST='',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ThemeBrowserTests(StaticLiveServerTestCase):
    def test_gallery_palette_preview_save_content_and_mobile(self):
        tenant = Tenant.objects.create(nome='NovaHost', subdomain='novahost')
        admin = User.objects.create_user('theme-browser@example.test', 'Theme!Password2026', tenant=tenant, tipo='ADMIN')
        self.client.force_login(admin)
        session = self.client.cookies['sessionid'].value
        url = self.live_server_url.replace('localhost', 'novahost.localhost')
        errors = []
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            context = browser.new_context(viewport={'width':1600, 'height':1000})
            context.add_cookies([{'name':'sessionid', 'value':session, 'url':url}])
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url+'/painel/estilo')
            expect(page.locator('.theme-card')).to_have_count(15)
            first = page.locator('.theme-card').first
            first.locator('[data-color="#dc2626"]').click()
            expect(first.locator('output')).to_have_text('#dc2626')
            expect(first.locator('[data-color="#dc2626"]')).to_have_attribute('aria-pressed', 'true')
            self.assertEqual(first.locator('.theme-mini').evaluate("el => getComputedStyle(el).getPropertyValue('--theme-primary').trim()"), '#dc2626')
            first.get_by_role('button', name='Visualizar', exact=True).click()
            dialog = page.locator('#theme-preview-dialog')
            expect(dialog).to_be_visible()
            expect(page.locator('#preview-status')).to_contain_text('Esta prévia não altera')
            frame = page.frame_locator('iframe')
            expect(frame.locator('body')).to_have_attribute('inert', '')
            expect(frame.locator('body')).to_have_class('public-booking-page tenant-content tenant-site theme-minimalista')
            page.screenshot(path='/tmp/tenant-theme-preview.png')
            dialog.get_by_role('button', name='Fechar', exact=True).click()
            first.get_by_role('button', name='Salvar e aplicar').click()
            expect(page.locator('#theme-status')).to_contain_text('Minimalista')
            page.screenshot(path='/tmp/tenant-themes-desktop.png', full_page=True)
            for width in (768,390,320):
                page.set_viewport_size({'width':width,'height':844})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            page.screenshot(path='/tmp/tenant-themes-mobile.png', full_page=True)
            page.goto(url+'/painel/estilo/conteudo/')
            page.locator('#profession-suggestion').select_option(label='Podologia')
            page.get_by_role('button', name='Usar sugestão no título').click()
            expect(page.locator('#id_title')).to_have_value('Seus pés merecem cuidado especial')
            page.locator('#id_description').fill('Cuidado e bem-estar para você.')
            page.locator('#id_button_text').fill('Conheça nossos serviços')
            page.get_by_role('button', name='Salvar e aplicar').click()
            page.goto(url+'/')
            expect(page.locator('.hero h1')).to_have_text('Seus pés merecem cuidado especial')
            expect(page.locator('.hero-copy>p')).to_contain_text('Cuidado e bem-estar para você.')
            expect(page.locator('.hero-primary')).to_have_attribute('href', '#servicos')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 320)
            page.screenshot(path='/tmp/tenant-theme-public-mobile.png', full_page=True)
            self.assertEqual(errors, [])
            browser.close()
        theme = TenantTheme.objects.get(tenant=tenant)
        self.assertEqual((theme.style, theme.primary_color), ('minimalista','#dc2626'))
