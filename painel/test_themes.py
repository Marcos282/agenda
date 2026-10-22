from datetime import time, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from agenda.test_booking import BookingFixture
from agenda.booking import registrar_falta
from pagamentos.models import CheckoutAcesso, PagamentoAcesso
from tenants.models import TenantTheme
from usuarios.models import User
from .theme_forms import ContentForm
from tenants.themes import THEMES, PALETTE, contrast_color, luminance, tokens


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost'], DEV_PUBLIC_HOST='',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class TenantThemeTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin = User.objects.create_user('theme-admin@example.test', 'Theme!Password2026', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.url = reverse('painel:estilo')
        self.content_url = reverse('painel:estilo_conteudo')
        self.preview_url = reverse('painel:estilo_preview')
        self.restore_url = reverse('painel:estilo_restaurar')
        self.host = {'HTTP_HOST': 'marcos.localhost'}
        checkout = CheckoutAcesso.objects.create(tenant=self.tenant, valor=30, retorno_url='https://marcos.localhost/', expira_em=timezone.now()+timedelta(hours=1))
        PagamentoAcesso.objects.create(payment_id='theme-test-payment', checkout=checkout, status='approved')
        booking = self.book()
        with patch('django.utils.timezone.now', return_value=booking.inicio):
            registrar_falta(tenant=self.tenant, administrador=self.admin, agendamento_id=booking.pk)

    def apply(self, **kwargs):
        return self.client.post(self.url, {'style': 'odontologia', 'primary_color': '#2196f3', **kwargs}, **self.host)

    def snapshot(self):
        # Every concrete field in every operational model, not just row counts.
        return {m._meta.label: list(m.objects.order_by(m._meta.pk.name).values())
                for m in apps.get_models() if m._meta.app_label in {
                    'tenants', 'usuarios', 'agenda', 'catalogo', 'profissionais', 'pagamentos', 'whatsapp'
                } and m is not TenantTheme}

    def test_tenant_isolation_and_field_allowlist(self):
        other = TenantTheme.objects.create(tenant=self.other, style='retro', title='Outro site')
        before = TenantTheme.objects.filter(pk=other.pk).values().get()
        self.assertEqual(self.apply(tenant_id=self.other.pk, title='Injetado', plano='PROFISSIONAL').status_code, 302)
        other.refresh_from_db()
        self.assertEqual(before, TenantTheme.objects.filter(pk=other.pk).values().get())
        own = TenantTheme.objects.get(tenant=self.tenant)
        self.assertEqual(own.style, 'odontologia')
        self.assertEqual(own.title, '')
        self.assertEqual(self.client.post(self.url, {'style':'retro','primary_color':'#ffffff'}, HTTP_HOST='wanessa.localhost').status_code, 403)

    def test_operational_integrity_apply_content_restore(self):
        before = self.snapshot()
        self.apply()
        self.assertEqual(before, self.snapshot())
        self.client.post(self.content_url, {'title':'Consulta', 'subtitle':'Cuidado', 'description':'Descrição', 'button_text':'Marcar consulta', 'icon':'🦷'}, **self.host)
        self.assertEqual(before, self.snapshot())
        self.client.post(self.restore_url, {'confirm':'yes'}, **self.host)
        self.assertEqual(before, self.snapshot())

    def test_gallery_palettes_and_persistence(self):
        self.apply(style='podologia', primary_color='#66bfbf')
        response = self.client.get(self.url, **self.host)
        self.assertEqual(response.content.count(b'class="theme-card"'), len(THEMES))
        self.assertEqual(response.content.count(b'type="color"'), len(THEMES))
        self.assertEqual(response.content.count(b'class="theme-swatch"'), len(THEMES)*len(PALETTE))
        self.assertContains(response, 'Podologia <small>Publicado</small>', html=False)
        self.assertContains(response, 'value="#66bfbf"')
        self.assertEqual(TenantTheme.objects.get(tenant=self.tenant).primary_color, '#66bfbf')
        self.assertNotContains(response, 'class="tenant-content')

    def test_preview_is_temporary_and_inert(self):
        self.apply()
        before = list(TenantTheme.objects.values())
        response = self.client.post(self.preview_url, {'style':'dark-premium','primary_color':'#ff6b00'}, **self.host)
        self.assertContains(response, 'theme-dark-premium')
        self.assertContains(response, 'inert')
        self.assertIn("form-action 'none'", response['Content-Security-Policy'])
        self.assertEqual(before, list(TenantTheme.objects.values()))
        public = self.client.get(reverse('home'), **self.host)
        self.assertContains(public, 'theme-odontologia')
        self.assertNotContains(public, 'theme-dark-premium')

    def test_preview_does_not_create_configuration(self):
        self.client.post(self.preview_url, {'style':'retro','primary_color':'#b34b32'}, **self.host)
        self.assertFalse(TenantTheme.objects.filter(tenant=self.tenant).exists())

    def test_platform_and_other_tenant_unchanged(self):
        public = Client()
        before = public.get('/', HTTP_HOST='localhost').content
        other = public.get('/', HTTP_HOST='wanessa.localhost').content
        self.apply()
        self.assertEqual(before, public.get('/', HTTP_HOST='localhost').content)
        self.assertEqual(other, public.get('/', HTTP_HOST='wanessa.localhost').content)
        with override_settings(TENANT_BASE_DOMAIN='tacombinado.net', ALLOWED_HOSTS=['.tacombinado.net']):
            response = public.get('/', HTTP_HOST='tacombinado.net')
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'tenant-themes.css')
            self.assertNotContains(response, 'theme-odontologia')

    def test_booking_flow_after_theme_change(self):
        self.apply(style='personal-trainer', primary_color='#ff6b00')
        self.client.logout()
        response = self.client.get(self.slots_url(), **self.host)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(self.slots_url(), self.payload(hora='09:47'), **self.host)
        self.assertEqual(response.status_code, 302)
        from agenda.models import Agendamento
        booking = Agendamento.objects.get(status='CONFIRMADO')
        self.assertEqual(booking.tenant_id, self.tenant.pk)
        self.assertEqual(str(booking.valor), '40.00')

    def test_restore_requires_confirmation_and_keeps_files(self):
        theme = TenantTheme.objects.create(tenant=self.tenant, style='retro', title='Customizado', hero_image=f'tenants/{self.tenant.pk}/kept.webp')
        self.assertEqual(self.client.get(self.restore_url, **self.host).status_code, 405)
        self.assertEqual(self.client.post(self.restore_url, {}, **self.host).status_code, 400)
        with patch.object(theme.hero_image.storage, 'delete') as delete:
            self.client.post(self.restore_url, {'confirm':'yes'}, **self.host)
            delete.assert_not_called()
        theme.refresh_from_db()
        self.assertEqual((theme.style, theme.title, theme.hero_image.name), ('original', '', ''))
        self.assertNotContains(self.client.get('/', **self.host), 'tenant-site theme-')

    def test_validation_roles_csrf_and_xss(self):
        for data in [{'style':'unknown','primary_color':'#2196f3'}, {'style':'retro','primary_color':'red'}, {'style':'retro','primary_color':'#123456;'}]:
            self.assertEqual(self.client.post(self.url, data, **self.host).status_code, 200)
            self.assertFalse(TenantTheme.objects.exists())
        self.client.post(self.content_url, {'title':'<script>alert(1)</script>', 'button_text':'Marcar consulta'}, **self.host)
        response = self.client.get('/', **self.host)
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertContains(response, 'href="#servicos">Marcar consulta')
        self.assertNotContains(response, '<script>alert(1)</script>')
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        for url in [self.url, self.content_url, self.preview_url, self.restore_url]:
            self.assertEqual(csrf.post(url, {}, **self.host).status_code, 403)
        professional = User.objects.create_user('theme-prof@example.test', 'Theme!Password2026', tenant=self.tenant, tipo='PROFISSIONAL')
        self.client.force_login(professional)
        for url in [self.url, self.content_url, self.preview_url, self.restore_url]:
            self.assertEqual(self.client.post(url, {}, **self.host).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url, **self.host).status_code, 302)

    @staticmethod
    def upload():
        buf = BytesIO()
        Image.new('RGB', (2400, 1200), 'blue').save(buf, 'PNG')
        return SimpleUploadedFile('test.png', buf.getvalue(), content_type='image/png')

    def test_upload_validation_optimization_isolation_and_preview(self):
        with TemporaryDirectory() as directory:
            from django.core.files.storage import FileSystemStorage
            storage = FileSystemStorage(location=directory)
            field = TenantTheme._meta.get_field('hero_image')
            with patch.object(field, 'storage', storage):
                before = list(TenantTheme.objects.values())
                preview = self.client.post(self.preview_url, {'preview_kind':'content', 'hero_image':self.upload()}, **self.host)
                self.assertContains(preview, 'data:image/webp;base64,')
                self.assertEqual(before, list(TenantTheme.objects.values()))
                self.assertEqual(self.client.post(self.content_url, {'hero_image':self.upload()}, **self.host).status_code, 302)
                theme = TenantTheme.objects.get(tenant=self.tenant)
                self.assertTrue(theme.hero_image.name.startswith(f'tenants/{self.tenant.pk}/'))
                with Image.open(theme.hero_image) as optimized:
                    self.assertEqual(optimized.format, 'WEBP')
                    self.assertEqual(optimized.size, (1920, 960))
                image_url = reverse('theme_image', args=['hero_image'])
                self.assertEqual(self.client.get(image_url, **self.host).status_code, 200)
                self.assertEqual(Client().get(image_url, HTTP_HOST='wanessa.localhost').status_code, 404)
                self.assertEqual(self.client.get(reverse('theme_image',args=['other']), **self.host).status_code, 404)
                original_name = theme.hero_image.name
                self.client.post(self.content_url, {'hero_image':self.upload()}, **self.host)
                theme.refresh_from_db()
                self.assertNotEqual(original_name, theme.hero_image.name)
                self.assertTrue(storage.exists(original_name))
                replacement_name = theme.hero_image.name
                self.client.post(self.restore_url, {'confirm':'yes'}, **self.host)
                self.assertTrue(storage.exists(original_name))
                self.assertTrue(storage.exists(replacement_name))
        for upload in [SimpleUploadedFile('bad.png', b'not an image'), SimpleUploadedFile('fake.svg', b'<svg/>')]:
            form = ContentForm({}, {'hero_image':upload}, instance=TenantTheme(tenant=self.tenant))
            self.assertFalse(form.is_valid())
        from tenants.theme_uploads import optimize_image
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            optimize_image(SimpleUploadedFile('huge.png', b'x'*(5*1024*1024+1)))

    def test_all_themes_valid_and_accessible_primary_contrast(self):
        for entry in THEMES:
            self.assertEqual(self.apply(style=entry[0], primary_color=entry[3]).status_code, 302)
            self.assertContains(self.client.get('/', **self.host), f'theme-{entry[0]}')
        for entry in THEMES:
            for color in [*PALETTE, '#ffffff', '#000000']:
                values = tokens(entry[0], color)
                for foreground, background in [(values['on_primary'], color), (values['accent_ink'], values['background'])]:
                    a, b = luminance(foreground), luminance(background)
                    self.assertGreaterEqual((max(a,b)+.05)/(min(a,b)+.05), 4.5)
        self.assertEqual(contrast_color('#ffffff'), '#000000')
        self.assertEqual(contrast_color('#000000'), '#ffffff')

    def test_tattoo_theme_content_and_preview(self):
        response = self.client.get(self.url, **self.host)
        self.assertContains(response, 'Estúdio de Tatuagem')
        response = self.client.get(self.content_url, **self.host)
        self.assertContains(response, 'Sua história, marcada em arte')
        self.assertEqual(self.apply(style='tatuagem', primary_color='#d6a86c').status_code, 302)
        self.assertEqual(self.client.post(self.content_url, {
            'title':'Sua história, marcada em arte', 'icon':'✒', 'button_text':'Conheça nossos serviços'
        }, **self.host).status_code, 302)
        response = self.client.get('/', **self.host)
        self.assertContains(response, 'theme-tatuagem')
        self.assertContains(response, 'Sua história, marcada em arte')
        self.assertContains(response, '✒')
        theme = TenantTheme.objects.get(tenant=self.tenant)
        self.assertEqual((theme.style,theme.icon),('tatuagem','✒'))
        before = list(TenantTheme.objects.values())
        response = self.client.post(self.preview_url, {'style':'tatuagem','primary_color':'#dc2626'}, **self.host)
        self.assertContains(response, 'theme-tatuagem')
        self.assertEqual(before, list(TenantTheme.objects.values()))

    def test_image_can_be_disabled_reenabled_and_removed_independently(self):
        theme = TenantTheme.objects.create(tenant=self.tenant,
            hero_image=f'tenants/{self.tenant.pk}/hero.webp',
            background_image=f'tenants/{self.tenant.pk}/background.webp')
        response = self.client.post(self.content_url, {
            'hero_image_action':'hide', 'background_image_action':'show'
        }, **self.host)
        self.assertEqual(response.status_code, 302)
        theme.refresh_from_db()
        self.assertFalse(theme.hero_image_enabled)
        self.assertTrue(theme.hero_image.name)
        self.assertTrue(theme.background_image_enabled)
        response = self.client.get('/', **self.host)
        self.assertNotIn('hero_image', response.context['theme_media'])
        self.assertIn('background_image', response.context['theme_media'])
        self.client.post(self.content_url, {'hero_image_action':'show', 'background_image_action':'hide'}, **self.host)
        response = self.client.get('/', **self.host)
        self.assertIn('hero_image', response.context['theme_media'])
        self.assertNotIn('background_image', response.context['theme_media'])
        with patch.object(theme.hero_image.storage, 'delete') as delete:
            response = self.client.post(self.content_url, {'hero_image_action':'remove'}, **self.host)
            self.assertEqual(response.status_code, 302)
            delete.assert_not_called()
        theme.refresh_from_db()
        self.assertFalse(theme.hero_image.name)
        self.assertTrue(theme.background_image.name)
        self.assertFalse(theme.background_image_enabled)

    def test_preview_image_actions_do_not_persist(self):
        theme = TenantTheme.objects.create(tenant=self.tenant,
            hero_image=f'tenants/{self.tenant.pk}/hero.webp')
        for action in ['hide','remove']:
            response = self.client.post(self.preview_url, {
                'preview_kind':'content', 'hero_image_action':action
            }, **self.host)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('hero_image', response.context['theme_media'])
            theme.refresh_from_db()
            self.assertTrue(theme.hero_image.name)
            self.assertTrue(theme.hero_image_enabled)
        response = self.client.post(self.content_url, {
            'hero_image':self.upload(), 'hero_image_action':'remove'
        }, **self.host)
        self.assertEqual(response.status_code, 200)
        theme.refresh_from_db()
        self.assertTrue(theme.hero_image.name.endswith('hero.webp'))
