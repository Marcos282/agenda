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
        self.assertContains(response, 'Baixar QR Code')
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

    def test_professional_profile_photo_address_and_qr(self):
        from profissionais.models import Profissional
        professional = Profissional.objects.create(tenant=self.tenant, nome='João', foto='foto-teste.jpg')
        self.admin.endereco = 'Rua das Flores'
        self.admin.numero_endereco = '123'
        self.admin.bairro = 'Centro'
        self.admin.cidade = 'Rio de Janeiro'
        self.admin.estado = 'RJ'
        self.admin.save()
        response = self.client.get(self.page, {'profissional': professional.pk}, **self.host)
        self.assertContains(response, 'Foto de João')
        self.assertContains(response, 'Rua das Flores, 123')
        self.assertContains(response, 'Rio de Janeiro / RJ')
        self.assertContains(response, 'store-profile-photo')
        self.assertEqual(response.context['endereco_loja'], f'https://marcos.tacombinado.net/profissional/{professional.pk}/')
        store = self.client.get(self.image, **self.host)
        profile = self.client.get(self.image, {'profissional': professional.pk}, **self.host)
        self.assertEqual(profile.status_code, 200)
        self.assertNotEqual(store.content, profile.content)

    def test_professional_selector_cannot_cross_tenants(self):
        from profissionais.models import Profissional
        other = Profissional.objects.create(tenant=self.other, nome='Outro profissional')
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Inativo', ativo=False)
        for selected in [other.pk, inactive.pk, 'invalido']:
            for url in [self.page, self.image]:
                self.assertEqual(self.client.get(url, {'profissional': selected}, **self.host).status_code, 404)
