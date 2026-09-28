"""Browser smoke test against Django's disposable PostgreSQL test database.
Run: myenv/bin/python scripts/qa_agenda.py
Optional: CHROME_EXECUTABLE=/path/to/chrome QA_SCREENSHOTS=/tmp/agenda-qa
Do not run concurrently with manage.py test (same test database).
"""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barbe.settings')
import django
django.setup()

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.test.runner import DiscoverRunner
from django.test.testcases import LiveServerThread
from playwright.sync_api import sync_playwright, expect
from tenants.models import Tenant
from profissionais.models import Profissional
from usuarios.models import User
from agenda.models import Disponibilidade
from django.db import connections


def active_ids():
    # Playwright runs its own event loop; keep sync ORM calls in a separate thread.
    def read():
        try:
            return list(Disponibilidade.objects.filter(ativo=True).values_list('pk', flat=True))
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(read).result()

runner = DiscoverRunner(interactive=False, verbosity=0)
runner.setup_test_environment()
db_config = runner.setup_databases()
server = None
try:
    tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
    joao = Profissional.objects.create(tenant=tenant, nome='João')
    sandro = Profissional.objects.create(tenant=tenant, nome='Sandro')
    User.objects.create_user('visual@example.test', 'Visual-Test!2026', tenant=tenant, tipo='ADMIN')
    server = LiveServerThread('127.0.0.1', StaticFilesHandler)
    server.start(); server.is_ready.wait(timeout=10)
    if server.error:
        raise server.error
    base = f'http://marcos.localhost:{server.port}'
    folder = Path(os.environ.get('QA_SCREENSHOTS', '/tmp/agenda-qa')); folder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        options = {'headless': True}
        chrome = os.environ.get('CHROME_EXECUTABLE')
        if chrome:
            options['executable_path'] = chrome
        browser = playwright.chromium.launch(**options)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100}, locale='pt-BR')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/login/')
        page.get_by_label('E-mail').fill('visual@example.test')
        page.locator('[name="password"]').fill('Visual-Test!2026')
        page.get_by_role('button', name='Entrar', exact=True).click()
        page.wait_for_url('**/conta/')
        agenda = base + f'/painel/agenda/?profissional={joao.pk}&data=2026-09-30'
        page.goto(agenda)
        expect(page.locator('.agenda-status')).to_have_text('○ Agenda fechada')
        expect(page.locator('[data-timeline]')).to_have_count(0)
        page.screenshot(path=str(folder / 'desktop-fechada.png'), full_page=True)
        page.locator('[data-open-schedule]').first.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.locator('[name="periodos-0-hora_inicio"]').fill('09:00')
        page.locator('[name="periodos-0-hora_fim"]').fill('12:00')
        page.get_by_role('button', name='+ Adicionar período').click()
        page.locator('[name="periodos-1-hora_inicio"]').fill('13:00')
        page.locator('[name="periodos-1-hora_fim"]').fill('18:00')
        page.screenshot(path=str(folder / 'desktop-modal.png'), full_page=True)
        page.get_by_role('button', name='Salvar horários').click()
        expect(page.locator('.agenda-status')).to_have_text('● Agenda aberta')
        expect(page.locator('.timeline-block.free')).to_have_count(2)
        expect(page.locator('.timeline-block.closed')).to_have_count(1)
        assert len(active_ids()) == 2
        page.screenshot(path=str(folder / 'desktop-aberta.png'), full_page=True)
        page.get_by_role('link', name='Próximo dia').click()
        expect(page.locator('.agenda-status')).to_have_text('○ Agenda fechada')
        page.get_by_role('link', name='Dia anterior').click()
        page.locator(f'.professional-tab[href$="profissional={sandro.pk}"]').click()
        expect(page.locator('#professional-heading')).to_have_text('Sandro')
        expect(page.locator('.agenda-status')).to_have_text('○ Agenda fechada')
        page.goto(agenda)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(folder / 'mobile-aberta.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
        page.locator('[data-open-schedule]').first.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        assert page.locator('[name="periodos-0-hora_inicio"]').bounding_box()['width'] >= 135
        page.screenshot(path=str(folder / 'mobile-modal.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile modal overflow'
        # Save unchanged windows and verify their identity is preserved.
        ids = active_ids()
        page.get_by_role('button', name='Salvar horários').click()
        expect(page.locator('.agenda-status')).to_have_text('● Agenda aberta')
        assert active_ids() == ids
        # Backend errors remain in the accessible dialog and do not persist partial changes.
        page.locator('[data-open-schedule]').first.click()
        page.locator('[name="periodos-1-hora_inicio"]').fill('11:00')
        page.get_by_role('button', name='Salvar horários').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_text('Os períodos se sobrepõem. Ajuste os horários antes de salvar.')).to_be_visible()
        assert len(active_ids()) == 2
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)
        assert not errors, errors
        browser.close()
    print(f'Browser QA OK: desktop, mobile, modal, navigation, editing and overlap. Screenshots: {folder}')
finally:
    if server:
        server.terminate()
    runner.teardown_databases(db_config)
    runner.teardown_test_environment()
