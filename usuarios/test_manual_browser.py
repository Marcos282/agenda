from urllib.parse import urlsplit
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import sync_playwright, expect

from usuarios.manual_content import categories


@override_settings(DEBUG=True, ALLOWED_HOSTS=['localhost'], TENANT_BASE_DOMAIN='localhost',
                   DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='')
class ManualBrowserTests(StaticLiveServerTestCase):
    def test_navigation_search_feedback_and_responsive_layout(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            context.route('**/*', lambda route: route.continue_()
                          if urlsplit(route.request.url).hostname == 'localhost' else route.abort())
            page = context.new_page()
            errors, failed_assets = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: failed_assets.append(response.url) if response.status >= 400 else None)
            self.assertEqual(page.goto(self.live_server_url + '/manual/').status, 200)
            expect(page.locator('[data-group]:visible')).to_have_count(9)
            self.assertEqual(page.locator('figure').count(), page.locator('[data-tutorial]').count())
            self.assertEqual(page.locator('[data-video-player][src]').count(), 0)
            self.assertEqual(page.locator('[data-category-video]:visible').count(), 0)
            page.screenshot(path='/tmp/manual-desktop.png', full_page=False)
            search = page.get_by_role('searchbox')
            for term, target in [('CADASTRAR PROFISSIONAL', 'cadastrar-profissional'), ('personalizacao', 'personalizar-site'), ('abrir agenda', 'abrir-agenda'), ('duracao', 'vincular-servico')]:
                search.fill(term)
                expect(page.locator('#' + target)).to_be_visible()
            search.fill('zzznadaencontrado')
            expect(page.locator('#manual-empty')).to_be_visible()
            page.get_by_role('button', name='Limpar', exact=True).click()
            category_ids = ('primeiros-passos', 'profissionais', 'servicos', 'agenda',
                            'clientes', 'whatsapp', 'personalizacao', 'qr-code', 'renovacao')
            video_ids = {category['id']: category['video_id'] for category in categories()}
            for category_id in category_ids:
                page.locator(f'[data-category="{category_id}"]').click()
                player = page.locator(f'#{category_id} [data-video-player]')
                if video_ids[category_id]:
                    expect(player).to_have_attribute(
                        'src', f'https://www.youtube-nocookie.com/embed/{video_ids[category_id]}',
                    )
                    self.assertEqual(page.locator('[data-video-player][src]').count(), 1)
                    self.assertEqual(player.get_attribute('loading'), 'lazy')
                    self.assertNotIn('autoplay', player.get_attribute('allow'))
                else:
                    expect(page.locator(f'#{category_id} .manual-video-placeholder')).to_be_visible()
                    self.assertEqual(page.locator('[data-video-player][src]').count(), 0)
                self.assertTrue(page.locator(f'#{category_id}').evaluate(
                    "(category) => Boolean(category.querySelector('[data-category-video]').compareDocumentPosition(category.querySelector('.manual-category-heading')) & Node.DOCUMENT_POSITION_FOLLOWING)"
                ))
            page.locator('[data-category="profissionais"]').click()
            page.locator('#cadastrar-profissional > summary').click()
            expect(page.locator('#cadastrar-profissional')).to_have_attribute('open', '')
            player = page.locator('#profissionais .manual-video-placeholder')
            expect(player).to_be_visible()
            self.assertTrue(page.locator('#profissionais [data-category-video]').evaluate(
                "(video) => Boolean(video.compareDocumentPosition(video.parentElement.querySelector('.manual-category-heading')) & Node.DOCUMENT_POSITION_FOLLOWING)"
            ))
            self.assertTrue(page.locator('#profissionais .manual-video-player').evaluate(
                "(player) => Math.abs(player.getBoundingClientRect().width / player.getBoundingClientRect().height - 16 / 9) < 0.02"
            ))
            page.locator('[data-category="agenda"]').click()
            expect(page.locator('[data-group]:visible')).to_have_count(1)
            expect(page.locator('#agenda .manual-video-placeholder')).to_be_visible()
            self.assertEqual(page.locator('#profissionais [data-video-player][src]').count(), 0)
            page.locator('#abrir-agenda > summary').click()
            expect(page.locator('#abrir-agenda .manual-steps')).to_be_visible()
            page.locator('#abrir-agenda a[href="#vincular-servico"]').click()
            expect(page.locator('#vincular-servico')).to_have_attribute('open', '')
            box = page.locator('#vincular-servico [data-feedback]')
            box.get_by_role('button', name='👍 Sim', exact=True).click()
            expect(box.get_by_role('button', name='👍 Sim', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.reload()
            expect(page.locator('#vincular-servico [data-vote="sim"]')).to_have_attribute('aria-pressed', 'true')
            page.locator('#vincular-servico [data-vote="ajuda"]').click()
            expect(page.locator('#vincular-servico .manual-feedback-status')).to_contain_text('não abre um chamado')
            for width in (768, 390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                expect(page.locator('#manual-menu')).not_to_have_attribute('open', '')
                page.locator('#manual-menu > summary').click()
                page.locator('[data-category="qr-code"]').click()
                expect(page.locator('#qr-code')).to_be_visible()
                expect(page.locator('#manual-menu')).not_to_have_attribute('open', '')
                self.assertTrue(page.locator('#qr-code .manual-video-player').evaluate(
                    "(player) => Math.abs(player.getBoundingClientRect().width / player.getBoundingClientRect().height - 16 / 9) < 0.02"
                ))
            page.locator('#qr-loja > summary').click()
            page.screenshot(path='/tmp/manual-mobile.png', full_page=False)
            page.goto(self.live_server_url + '/manual/#primeiros-passos')
            player = page.locator('#primeiros-passos [data-video-player]')
            expect(player).to_be_in_viewport()
            expect(player).to_have_attribute(
                'src', f'https://www.youtube-nocookie.com/embed/{video_ids["primeiros-passos"]}',
            )
            expect(page.locator('#primeiros-passos [data-tutorial]').first).to_have_attribute('open', '')
            page.goto(self.live_server_url + '/manual/#profissionais')
            expect(page.locator('#profissionais .manual-video-placeholder')).to_be_visible()
            self.assertEqual(page.locator('[data-video-player][src]').count(), 0)
            self.assertEqual(errors, [])
            self.assertEqual(failed_assets, [])
            # Static content and native disclosure still work without JS.
            fallback = browser.new_context(java_script_enabled=False)
            fallback_page = fallback.new_page()
            fallback_page.goto(self.live_server_url + '/manual/')
            fallback_page.locator('#cadastrar-profissional > summary').click()
            expect(fallback_page.locator('#cadastrar-profissional .manual-steps')).to_be_visible()
            expect(fallback_page.locator('[data-search-ui]')).to_be_hidden()
            browser.close()
