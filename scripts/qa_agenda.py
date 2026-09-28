"""Browser smoke test against Django's disposable PostgreSQL test database.
Run: myenv/bin/python scripts/qa_agenda.py
Optional: CHROME_EXECUTABLE=/path/to/chrome QA_SCREENSHOTS=/tmp/agenda-qa
Do not run concurrently with manage.py test (same test database).
"""
import os
from datetime import timedelta, time
from django.utils import timezone
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
from catalogo.models import Servico, ProfissionalServico
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

def prepare_no_show(tenant_id, offer_id):
    from unittest.mock import patch
    from agenda.booking import reservar, instante_local
    def create():
        try:
            tenant = Tenant.objects.get(pk=tenant_id)
            offer = ProfissionalServico.objects.get(pk=offer_id)
            day = timezone.localdate() - timedelta(days=1)
            Disponibilidade.objects.create(tenant=tenant, profissional=offer.profissional, data=day,
                hora_inicio=time(9), hora_fim=time(12))
            customer = User.objects.get(email='customer-qa@example.test')
            with patch('django.utils.timezone.now', return_value=instante_local(day, time(8), tenant)):
                reservar(tenant=tenant, cliente=customer, oferta_id=offer_id, dia=day, hora=time(9),
                    nome='Cliente ausente', valor_exibido='40.00', duracao_exibida=40)
            return day.isoformat()
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(create).result()


runner = DiscoverRunner(interactive=False, verbosity=0)
runner.setup_test_environment()
db_config = runner.setup_databases()
server = None
try:
    tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
    joao = Profissional.objects.create(tenant=tenant, nome='João')
    sandro = Profissional.objects.create(tenant=tenant, nome='Sandro')
    service = Servico.objects.create(tenant=tenant, nome='Corte de cabelo')
    offer = ProfissionalServico.objects.create(tenant=tenant, profissional=joao, servico=service, valor='40.00', duracao_minutos=40)
    User.objects.create_user('visual@example.test', 'Visual-Test!2026', tenant=tenant, tipo='ADMIN')
    day = (timezone.localdate() + timedelta(days=2)).isoformat()
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
        page.goto(base + '/')
        expect(page.locator('.service-card')).to_have_count(1)
        page.screenshot(path=str(folder / 'home-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Homepage mobile overflow'
        page.screenshot(path=str(folder / 'home-mobile.png'), full_page=True)
        page.get_by_label('Buscar serviço ou profissional').fill('Não existe')
        page.get_by_role('button', name='Buscar →').click()
        expect(page.get_by_role('heading', name='Nenhum serviço encontrado')).to_be_visible()
        page.goto(f'http://localhost:{server.port}/')
        expect(page.get_by_role('heading', name='Salões de beleza')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Platform mobile overflow'
        page.screenshot(path=str(folder / 'plataforma-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1100})
        page.screenshot(path=str(folder / 'plataforma-desktop.png'), full_page=True)
        page.get_by_label('Endereço do estabelecimento').fill('marcos')
        page.get_by_role('button', name='Encontrar estabelecimento →').click()
        page.wait_for_url(lambda url: url.startswith(base + '/'))
        expect(page.locator('.service-card')).to_have_count(1)
        page.set_viewport_size({'width': 1440, 'height': 1100})
        page.goto(base + '/loja/')
        expect(page.locator('.product-card')).to_have_count(1)
        page.screenshot(path=str(folder / 'loja-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Shop mobile overflow'
        page.screenshot(path=str(folder / 'loja-mobile.png'), full_page=True)
        page.get_by_role('link', name='Ver serviço', exact=False).last.click()
        expect(page.get_by_role('heading', name='Corte de cabelo', exact=True, level=1)).to_be_visible()
        expect(page.get_by_text('40 minutos de atendimento')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Shop details overflow'
        page.screenshot(path=str(folder / 'loja-detalhe-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1100})
        page.goto(base + '/login/')
        page.get_by_label('E-mail').fill('visual@example.test')
        page.locator('[name="password"]').fill('Visual-Test!2026')
        page.get_by_role('button', name='Entrar', exact=True).click()
        page.wait_for_url('**/conta/')
        page.goto(base + '/painel/whatsapp/')
        expect(page.get_by_role('heading', name='WhatsApp', exact=True)).to_be_visible()
        expect(page.locator('input[name=antecedencia_minutos]')).to_have_value('120')
        page.locator('input[name=antecedencia_minutos]').fill('90')
        page.get_by_role('button', name='Salvar configurações').click()
        expect(page.locator('input[name=antecedencia_minutos]')).to_have_value('90')
        page.screenshot(path=str(folder / 'whatsapp-desktop.png'), full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(folder / 'whatsapp-mobile.png'), full_page=True)
        page.set_viewport_size({'width':1280,'height':900})
        agenda = base + f'/painel/agenda/?profissional={joao.pk}&data={day}'
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
        # A single runtime variable recolors both shared buttons and agenda accents.
        before = page.locator('.agenda-button.secondary').first.evaluate('(el) => getComputedStyle(el).color')
        page.evaluate("document.documentElement.style.setProperty('--brand-color', '#65439a')")
        after = page.locator('.agenda-button.secondary').first.evaluate('(el) => getComputedStyle(el).color')
        assert before != after, 'Theme variable did not recolor agenda controls'
        page.evaluate("document.documentElement.style.removeProperty('--brand-color')")

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
        # Full customer journey, including signup return, confirmation, admin display and cancellation.
        customer_context = browser.new_context(viewport={'width': 1280, 'height': 950}, locale='pt-BR')
        customer = customer_context.new_page()
        customer.on('pageerror', lambda error: errors.append(str(error)))
        customer.goto(base + f'/loja/{offer.pk}/')
        customer.get_by_role('link', name='Agendar horário →').click()
        customer.get_by_label('Escolha a data').fill(day)
        customer.get_by_role('button', name='Ver horários disponíveis →').click()
        customer.get_by_role('link', name='Entrar para agendar').click()
        customer.get_by_role('link', name='Criar conta', exact=True).first.click()
        customer.get_by_label('E-mail').fill('customer-qa@example.test')
        customer.get_by_label('WhatsApp', exact=False).fill('(11) 99999-1234')
        customer.locator('[name="password1"]').fill('Customer-QA!2026')
        customer.locator('[name="password2"]').fill('Customer-QA!2026')
        customer.get_by_role('button', name='Cadastrar', exact=True).click()
        customer.get_by_label('E-mail').fill('customer-qa@example.test')
        customer.locator('[name="password"]').fill('Customer-QA!2026')
        customer.get_by_role('button', name='Entrar', exact=True).click()
        customer.wait_for_url(f'**/agendamentos/servico/{offer.pk}/{day}/')
        customer.get_by_label('Seu nome').fill('Cliente de teste')
        contact = customer.locator('[name=whatsapp]')
        expect(contact).to_have_value('+5511999991234')
        contact.fill('')
        assert contact.evaluate('(el) => el.required && !el.checkValidity()'), 'WhatsApp must be required at confirmation'
        contact.fill('(11) 99999-1234')
        customer.locator('.booking-slot').filter(has=customer.locator('[value="09:00"]')).click()
        customer.screenshot(path=str(folder / 'booking-desktop.png'), full_page=True)
        customer.set_viewport_size({'width': 390, 'height': 844})
        assert customer.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Booking mobile overflow'
        customer.screenshot(path=str(folder / 'booking-mobile.png'), full_page=True)
        customer.get_by_role('button', name='Confirmar agendamento →').click()
        expect(customer.get_by_role('heading', name='Seu horário está reservado.')).to_be_visible()
        customer.screenshot(path=str(folder / 'booking-confirmed-mobile.png'), full_page=True)
        page.goto(agenda)
        expect(page.locator('.timeline-block.booked')).to_have_count(1)
        expect(page.locator('.timeline-block.booked')).to_contain_text('Cliente de teste')
        page.screenshot(path=str(folder / 'agenda-booked-mobile.png'), full_page=True)
        customer.get_by_text('Precisa cancelar?', exact=True).click()
        customer.get_by_role('button', name='Confirmar cancelamento').click()
        expect(customer.get_by_role('heading', name='Agendamento cancelado')).to_be_visible()
        page.reload()
        expect(page.locator('.timeline-block.booked')).to_have_count(0)
        page.get_by_role('link', name='+ Novo agendamento', exact=True).click()
        page.locator('input[name=nome]').fill('Cliente no painel')
        page.get_by_label('WhatsApp').fill('(21) 99999-5678')
        page.screenshot(path=str(folder / 'panel-customer-text-mobile.png'), full_page=True)
        page.get_by_role('button', name='Escolher horário →').click()
        expect(page.get_by_text('Cliente: Cliente no painel', exact=False)).to_be_visible()
        page.locator('.booking-slot').filter(has=page.locator('[value="09:00"]')).click()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Panel booking mobile overflow'
        page.screenshot(path=str(folder / 'panel-booking-mobile.png'), full_page=True)
        page.get_by_role('button', name='Confirmar agendamento →').click()
        expect(page.locator('.timeline-block.booked')).to_have_count(1)
        expect(page.locator('.timeline-block.booked')).to_contain_text('Cliente no painel')
        customer.goto(base + '/agendamentos/')
        expect(customer.locator('.booking-list article')).to_have_count(1)
        page.locator('.timeline-block.booked').click()
        page.get_by_role('dialog').get_by_role('link', name='Cancelar agendamento', exact=True).click()
        expect(page.get_by_role('heading', name='Cancelar agendamento')).to_be_visible()
        expect(page.get_by_text('Cliente no painel', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Cancel confirmation mobile overflow'
        page.screenshot(path=str(folder / 'panel-cancel-mobile.png'), full_page=True)
        page.get_by_role('button', name='Confirmar cancelamento').click()
        expect(page.locator('.timeline-block.booked')).to_have_count(0)
        customer.reload()
        expect(customer.locator('.booking-list .booking-status').filter(has_text='Cancelado')).to_have_count(1)
        absence_day = prepare_no_show(tenant.pk, offer.pk)
        page.goto(base + f'/painel/agenda/?profissional={joao.pk}&data={absence_day}')
        page.locator('.timeline-block.booked').click()
        page.get_by_role('dialog').get_by_role('link', name='Marcar falta', exact=True).click()
        expect(page.get_by_role('heading', name='Registrar falta')).to_be_visible()
        page.get_by_role('button', name='Confirmar falta').click()
        expect(page.locator('.timeline-block.no-show')).to_have_count(1)
        expect(page.locator('.timeline-block.no-show')).to_contain_text('Não compareceu')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'No-show agenda mobile overflow'
        page.screenshot(path=str(folder / 'panel-no-show-mobile.png'), full_page=True)
        customer.reload()
        expect(customer.locator('.booking-list .booking-status').filter(has_text='Não compareceu')).to_have_count(1)
        page.get_by_role('link', name='Clientes', exact=True).click()
        page.get_by_label('Buscar cliente ou WhatsApp').fill('(11) 99999-1234')
        page.get_by_role('button', name='Buscar', exact=True).click()
        expect(page.locator('.client-row')).to_have_count(1)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Customer list mobile overflow'
        page.screenshot(path=str(folder / 'clients-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1100})
        page.screenshot(path=str(folder / 'clients-desktop.png'), full_page=True)
        page.get_by_role('link', name='Ver histórico →').click()
        expect(page.get_by_role('heading', name='Histórico de agendamentos')).to_be_visible()
        expect(page.locator('.client-status.cancelado')).to_have_count(1)
        expect(page.locator('.client-status.nao_compareceu')).to_have_count(1)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Customer history mobile overflow'
        page.screenshot(path=str(folder / 'client-history-mobile.png'), full_page=True)
        page.goto(base + '/painel/clientes/?q=21999995678')
        expect(page.locator('.client-row')).to_have_count(1)
        expect(page.locator('.client-row')).to_contain_text('Cliente no painel')
        page.get_by_role('link', name='Ver histórico →').click()
        expect(page.locator('.client-status.cancelado')).to_have_count(1)
        customer_context.close()
        assert not errors, errors
        browser.close()
    print(f'Browser QA OK: desktop, mobile, modal, navigation, editing and overlap. Screenshots: {folder}')
finally:
    if server:
        server.terminate()
    runner.teardown_databases(db_config)
    runner.teardown_test_environment()
