import base64
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from tenants.logo_generation import claim_job, process_job, validate_image
from tenants.models import LogoGeneration, LogoSettings, Tenant, TenantTheme
from usuarios.models import User

from .test_logo_generation import png_bytes


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost'], DEV_PUBLIC_HOST='',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LogoBrowserTests(StaticLiveServerTestCase):
    def test_modal_approval_and_history_on_desktop_and_mobile(self):
        LogoSettings.objects.update_or_create(pk=1, defaults={'enabled': True})
        storage = LogoGeneration._meta.get_field('image').storage
        tmp = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(storage, 'location', tmp))
        theme_storage = TenantTheme._meta.get_field('logo_image').storage
        self.enterContext(patch.object(theme_storage, 'location', tmp))
        fixtures = []
        for width in (1440, 390, 320):
            subdomain = f'logo-{width}'
            tenant = Tenant.objects.create(nome='Salão Único', subdomain=subdomain)
            user = User.objects.create_user(f'{subdomain}@example.test', 'unused', tenant=tenant, tipo='ADMIN')
            client = Client()
            client.force_login(user)
            cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
            fixtures.append((width, subdomain, cookie))

        def run_worker():
            try:
                valid = validate_image(base64.b64encode(png_bytes()))
                with patch('tenants.logo_generation.generate_image', return_value=(valid, 'req_test', {})):
                    process_job(claim_job())
            finally:
                connection.close()

        with sync_playwright() as playwright, ThreadPoolExecutor(max_workers=1) as executor:
            browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            for width, subdomain, cookie in fixtures:
                with self.subTest(width=width):
                    host = f'{subdomain}.localhost'
                    root = self.live_server_url.replace('localhost', host)
                    context = browser.new_context(viewport={'width': width, 'height': 850})
                    context.set_default_timeout(10000)
                    context.route('**/*', lambda route: route.continue_()
                                  if urlsplit(route.request.url).hostname == host else route.abort())
                    context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': cookie, 'url': root}])
                    page = context.new_page()
                    self.assertEqual(page.goto(root + reverse('painel:estilo_conteudo')).status, 200)
                    page.get_by_role('button', name='Criar logomarca com IA').click()
                    modal = page.get_by_role('dialog')
                    expect(modal.get_by_label('Nome do estabelecimento')).to_have_value('Salão Único')
                    expect(modal.get_by_text('Você possui 3 gerações disponíveis.')).to_be_visible()
                    self.assertLessEqual(modal.evaluate('(el) => el.scrollWidth'), width)
                    modal.get_by_label('Segmento de atuação').fill('Salão de beleza')
                    with page.expect_response(lambda response: response.url.endswith('/logomarcas/gerar/')) as queued:
                        modal.get_by_role('button', name='Gerar logomarca', exact=True).click()
                    self.assertEqual(queued.value.status, 200)
                    expect(modal.get_by_text('Estamos criando sua logomarca')).to_be_visible()
                    executor.submit(run_worker).result(timeout=15)
                    expect(modal.get_by_alt_text('Prévia da logomarca gerada')).to_be_visible(timeout=10000)
                    page.wait_for_function("() => document.querySelector('.logo-dialog img')?.naturalWidth > 0")
                    expect(modal.get_by_text('Você possui 2 gerações disponíveis.')).to_be_visible()
                    expect(modal.get_by_role('link', name='Baixar imagem')).to_be_visible()
                    published = root + reverse('theme_image', args=['logo_image'])
                    open_modal = page.get_by_role('button', name='Criar logomarca com IA')
                    for close in (
                        modal.get_by_role('button', name='Fechar', exact=True).click,
                        modal.get_by_role('button', name='Fechar modal').click,
                        lambda: page.keyboard.press('Escape'),
                    ):
                        close()
                        expect(modal).to_be_hidden()
                        expect(open_modal).to_be_focused()
                        self.assertEqual(context.request.get(published).status, 404)
                        open_modal.click()
                        expect(modal.get_by_alt_text('Prévia da logomarca gerada')).to_be_visible()
                        expect(modal.get_by_text('Você possui 2 gerações disponíveis.')).to_be_visible()

                    history = context.new_page()
                    history.goto(root + reverse('painel:logo_history'))
                    expect(history.get_by_role('link', name='Baixar imagem')).to_have_count(1)
                    history.close()
                    modal.get_by_role('button', name='Aplicar logomarca').click()
                    expect(modal.get_by_text('Logomarca aplicada ao seu site.')).to_be_visible()
                    modal.get_by_role('button', name='Fechar', exact=True).click()
                    success = page.get_by_text('Logomarca criada por IA e aplicada com sucesso')
                    thumbnail = page.get_by_alt_text('Ver logomarca atual')
                    upload = page.locator('input[type=file][name=logo_image]')
                    expect(success).to_be_visible()
                    expect(thumbnail).to_be_visible()
                    expect(upload).to_be_hidden()
                    page.wait_for_function("() => document.querySelector('[data-saved-logo-thumbnail]').naturalWidth > 0")
                    page.reload()
                    expect(success).to_be_visible()
                    expect(thumbnail).to_be_visible()
                    expect(upload).to_be_hidden()
                    page.get_by_text('Alterar logomarca', exact=True).click()
                    expect(upload).to_be_visible()
                    expect(upload).to_have_value('')
                    page.get_by_role('link', name='Minhas logomarcas').click()
                    expect(page.get_by_role('heading', name='Minhas logomarcas')).to_be_visible()
                    expect(page.get_by_role('link', name='Baixar imagem')).to_be_visible()
                    self.assertEqual(context.request.get(published).status, 200)
                    context.close()
            browser.close()

        self.assertEqual(TenantTheme.objects.exclude(logo_image='').count(), len(fixtures))
