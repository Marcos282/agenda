from django.test import TestCase, override_settings
from tenants.models import Tenant


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost'], DEV_PUBLIC_HOST='')
class PlatformStoreTests(TestCase):
    def test_platform_store_redirects_to_registration(self):
        response = self.client.get('/loja/', HTTP_HOST='localhost')
        self.assertRedirects(response, '/registro', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/loja/1/', HTTP_HOST='localhost').status_code, 404)

    def test_tenant_store_and_button_keep_their_destination(self):
        Tenant.objects.create(nome='Marcos', subdomain='marcos')
        self.assertEqual(self.client.get('/loja/', HTTP_HOST='marcos.localhost').status_code, 200)
        page = self.client.get('/', HTTP_HOST='marcos.localhost')
        self.assertContains(page, 'mobile-booking-button" href="/loja/"')
        platform = self.client.get('/', HTTP_HOST='localhost')
        self.assertContains(platform, 'mobile-booking-button" href="/registro"')
