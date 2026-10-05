from io import BytesIO

from PIL import Image
from django.test import TestCase, override_settings
from django.urls import reverse

from tenants.models import Tenant
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost')
class StoreQRCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        cls.other = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        cls.admin = User.objects.create_user('qr-admin@example.test', tenant=cls.tenant, tipo='ADMIN')
        cls.customer = User.objects.create_user('qr-customer@example.test', tenant=cls.tenant)
        cls.other_admin = User.objects.create_user('qr-other@example.test', tenant=cls.other, tipo='ADMIN')

    def setUp(self):
        self.client.force_login(self.admin)
        self.page = reverse('painel:loja_qrcode')
        self.image = reverse('painel:loja_qrcode_imagem')
        self.host = {'HTTP_HOST': 'marcos.localhost:8001'}

    def test_public_url_preview_and_download(self):
        response = self.client.get(self.page, **self.host)
        self.assertContains(response, 'https://marcos.tacombinado.net/')
        self.assertEqual(response.context['endereco_loja'], 'https://marcos.tacombinado.net/')
        self.assertContains(response, 'data-copy-store-url')
        self.assertContains(response, 'Copiar endereço do site')
        image = self.client.get(self.image, **self.host)
        self.assertEqual(image['Content-Type'], 'image/png')
        with Image.open(BytesIO(image.content)) as png:
            self.assertEqual(png.format, 'PNG')
            self.assertEqual(png.width, png.height)
            self.assertGreaterEqual(png.width, 300)
        download = self.client.get(self.image, {'download': '1'}, **self.host)
        self.assertEqual(download.content, image.content)
        self.assertEqual(download['Content-Disposition'], 'attachment; filename="qrcode-marcos.png"')
        self.assertIn('no-store', download['Cache-Control'])
        self.client.force_login(self.other_admin)
        other = self.client.get(self.page, HTTP_HOST='wanessa.localhost')
        self.assertEqual(other.context['endereco_loja'], 'https://wanessa.tacombinado.net/')
        self.assertNotEqual(self.client.get(self.image, HTTP_HOST='wanessa.localhost').content, image.content)

    @override_settings(STORE_BASE_DOMAIN='lojas.example')
    def test_configured_domain(self):
        response = self.client.get(self.page, **self.host)
        self.assertEqual(response.context['endereco_loja'], 'https://marcos.lojas.example/')

    def test_admin_scope_and_read_only_routes(self):
        for url in [self.page, self.image]:
            self.assertEqual(self.client.post(url, **self.host).status_code, 405)
            self.assertEqual(self.client.get(url, HTTP_HOST='wanessa.localhost').status_code, 403)
        self.client.force_login(self.customer)
        for url in [self.page, self.image]:
            self.assertEqual(self.client.get(url, **self.host).status_code, 403)
        self.client.logout()
        for url in [self.page, self.image]:
            self.assertEqual(self.client.get(url, **self.host).status_code, 302)

    def test_store_profile_ignores_old_professional_selection(self):
        from profissionais.models import Profissional
        professional = Profissional.objects.create(tenant=self.tenant, nome='João', foto='foto-teste.jpg')
        self.admin.endereco = 'Rua das Flores'
        self.admin.numero_endereco = '123'
        self.admin.save()
        response = self.client.get(self.page, {'profissional': professional.pk}, **self.host)
        self.assertNotContains(response, 'Rua das Flores, 123')
        self.assertNotContains(response, 'Foto de João')
        self.assertNotContains(response, 'qr-profissional')
        self.assertContains(response, f'data-photo="{reverse("painel:profissional_foto", args=[professional.pk])}"')
        self.assertEqual(response.context['endereco_loja'], 'https://marcos.tacombinado.net/')
        self.assertEqual(self.client.get(self.image, **self.host).content,
                         self.client.get(self.image, {'profissional': professional.pk}, **self.host).content)

    def test_professional_cards_and_tenant_scoped_qr(self):
        from unittest.mock import patch
        from profissionais.models import Profissional
        professional = Profissional.objects.create(tenant=self.tenant, nome='Ana')
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Inativo', ativo=False)
        foreign = Profissional.objects.create(tenant=self.other, nome='Outra loja')
        url = f'https://marcos.tacombinado.net/profissional/{professional.pk}/'
        response = self.client.get(self.page, **self.host)
        self.assertContains(response, 'Ana')
        self.assertContains(response, f'data-url="{url}"')
        self.assertContains(response, f'data-photo=""')
        self.assertNotContains(response, 'Inativo')
        self.assertNotContains(response, 'Outra loja')
        image_url = reverse('painel:profissional_qrcode_imagem', args=[professional.pk])
        with patch('painel.loja_qrcode_views.qrcode.QRCode.add_data', autospec=True) as add_data:
            image = self.client.get(image_url, **self.host)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(add_data.call_args.args[1], url)
        for unavailable in [inactive, foreign]:
            route = reverse('painel:profissional_qrcode_imagem', args=[unavailable.pk])
            self.assertEqual(self.client.get(route, **self.host).status_code, 404)
        self.assertEqual(self.client.post(image_url, **self.host).status_code, 405)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(image_url, **self.host).status_code, 403)
