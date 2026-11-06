"""Real-browser coverage using a disposable PostgreSQL database."""
from pathlib import Path
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect
from tenants.models import Tenant, TenantTheme
from tenants.themes import THEMES
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost'], DEV_PUBLIC_HOST='',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ThemeBrowserTests(StaticLiveServerTestCase):
    def test_responsive_banner_strip_and_visibility(self):
        tenant = Tenant.objects.create(nome='NovaHost', subdomain='novahost')
        theme = TenantTheme.objects.create(
            tenant=tenant, style='tatuagem',
            hero_image=f'tenants/{tenant.pk}/desktop.webp',
            background_image=f'tenants/{tenant.pk}/mobile.webp',
        )
        url = self.live_server_url.replace('localhost', 'novahost.localhost')
        desktop_url = reverse('theme_image', args=['hero_image'])
        mobile_url = reverse('theme_image', args=['background_image'])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            for width in [1440, 769, 768, 390, 320]:
                with self.subTest(width=width):
                    page = browser.new_page(viewport={'width': width, 'height': 1000})
                    requests = []
                    page.on('request', lambda request: requests.append(request.url))
                    for image_url in [desktop_url, mobile_url]:
                        page.route('**' + image_url + '*', lambda route: route.fulfill(
                            content_type='image/svg+xml',
                            body='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="green"/></svg>',
                        ))
                    page.goto(url + '/')
                    image = page.locator('.hero-banner img')
                    expected = desktop_url if width > 768 else mobile_url
                    other = mobile_url if width > 768 else desktop_url
                    expect(image).to_be_visible()
                    self.assertTrue(image.evaluate('el => el.complete && el.naturalWidth > 0'))
                    self.assertIn(expected, image.evaluate('el => el.currentSrc'))
                    self.assertEqual(image.evaluate('el => getComputedStyle(el).objectFit'), 'cover')
                    self.assertEqual(len([request for request in requests if expected in request]), 1)
                    self.assertFalse(any(other in request for request in requests))
                    expect(page.locator('.hero-copy, .hero-art')).to_have_count(0)
                    hero = page.locator('.hero').bounding_box()
                    self.assertEqual(hero['height'], 252 if width > 768 else 154)
                    banner = page.locator('.hero-banner').bounding_box()
                    self.assertEqual((banner['width'], banner['height']), (hero['width'], hero['height']))
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    page.close()
            browser.close()
        for field, width in [('background_image_enabled', 768), ('hero_image_enabled', 769)]:
            setattr(theme, field, False)
            theme.save(update_fields=[field])
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': width, 'height': 1000})
                page.goto(url + '/')
                expect(page.locator('.hero-banner')).to_be_hidden()
                expect(page.locator('.hero h1')).to_have_text('NovaHost')
                self.assertEqual(page.locator('.hero h1 span').bounding_box()['width'], 1)
                browser.close()

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
            expect(page.locator('.theme-card')).to_have_count(len(THEMES))
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
            expect(page.locator('.hero h1')).to_have_text('NovaHost')
            expect(page.locator('.hero-copy, .hero-art')).to_have_count(0)
            expect(page.locator('.hero-actions, .hero-primary, .hero a')).to_have_count(0)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 320)
            page.screenshot(path='/tmp/tenant-theme-public-mobile.png', full_page=True)
            self.assertEqual(errors, [])
            browser.close()
        theme = TenantTheme.objects.get(tenant=tenant)
        self.assertEqual((theme.style, theme.primary_color), ('minimalista','#dc2626'))
