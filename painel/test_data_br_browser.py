from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase
from playwright.sync_api import sync_playwright


class BrazilianDatePickerBrowserTests(SimpleTestCase):
    def test_calendar_is_above_trigger_and_only_brazilian_input_is_visible(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            for locale, width in [('en-US', 1280), ('pt-BR', 390)]:
                with self.subTest(locale=locale, width=width):
                    context = browser.new_context(locale=locale, viewport={'width': width, 'height': 900})
                    page = context.new_page()
                    page.set_content('<style>:root{--surface:white;--text:#24312b;--line:#ddd;--brand-color:#287454;--focus:#8b9}input{display:block;width:100%}</style>'
                        '<div style="height:500px"></div><form><label>Data do atendimento<input name="data" data-date-br="1" value="12/11/2026"></label></form>')
                    page.add_style_tag(path=str(Path(settings.BASE_DIR) / 'painel/static/painel/data-br.css'))
                    page.add_script_tag(path=str(Path(settings.BASE_DIR) / 'painel/static/painel/data-br.js'))
                    self.assertEqual(page.locator('input:visible').count(), 1)
                    trigger = page.get_by_role('button', name='Escolher data no calendário')
                    trigger.click()
                    popup = page.get_by_role('dialog')
                    self.assertTrue(popup.is_visible())
                    popup_box, trigger_box = popup.bounding_box(), trigger.bounding_box()
                    self.assertLessEqual(popup_box['y'] + popup_box['height'], trigger_box['y'] - 7)
                    self.assertGreaterEqual(popup_box['x'], 0)
                    self.assertLessEqual(popup_box['x'] + popup_box['width'], width)
                    page.get_by_role('button', name='Próximo mês').click()
                    self.assertIn('dezembro', popup.inner_text().lower())
                    page.get_by_role('button', name='Mês anterior').click()
                    page.locator('[data-date="2026-11-14"]').click()
                    self.assertEqual(page.locator('[name=data]').input_value(), '14/11/2026')
                    self.assertFalse(popup.is_visible())
                    self.assertEqual(page.locator('form').evaluate('el => [...new FormData(el).entries()]'), [['data', '14/11/2026']])
                    trigger.click()
                    page.keyboard.press('ArrowRight')
                    page.keyboard.press('Enter')
                    self.assertEqual(page.locator('[name=data]').input_value(), '15/11/2026')
                    trigger.click()
                    page.keyboard.press('Escape')
                    self.assertFalse(popup.is_visible())
                    self.assertTrue(trigger.evaluate('el => el === document.activeElement'))
                    context.close()
            browser.close()
