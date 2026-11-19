from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from tenants.models import Tenant
from usuarios.models import User
from usuarios.manual_content import MANUAL_VIDEOS, categories


PUBLIC = dict(TENANT_BASE_DOMAIN='tacombinado.net', DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='',
              ALLOWED_HOSTS=['tacombinado.net', '.tacombinado.net'],
              PLATFORM_PUBLIC_URL='https://tacombinado.net/')


@override_settings(**PUBLIC)
class ManualPublicTests(SimpleTestCase):
    def test_public_root_and_subdomains_without_tenant_queries(self):
        # SimpleTestCase rejects all DB queries, including tenant lookup.
        with override_settings(DEBUG=False, PLATFORM_PUBLIC_URL='https://tacombinado.net/'):
            original = self.client.get('/manual/', HTTP_HOST='tacombinado.net')
        self.assertNotIn('X-Robots-Tag', original)
        self.assertContains(original, '<link rel="canonical" href="https://tacombinado.net/manual/">', html=True)
        self.assertContains(original, 'Manual do Tá Combinado')
        for host in ('salao.tacombinado.net', 'inexistente.tacombinado.net'):
            response = self.client.get('/manual/', HTTP_HOST=host)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, original.content)
            self.assertIsNone(response.wsgi_request.tenant)
        self.assertEqual(self.client.head(reverse('manual'), HTTP_HOST='tacombinado.net').status_code, 200)
        self.assertEqual(self.client.post(reverse('manual'), HTTP_HOST='tacombinado.net').status_code, 405)

    def test_all_categories_links_and_examples_render(self):
        response = self.client.get(reverse('manual'), HTTP_HOST='tacombinado.net')
        content = categories()
        self.assertEqual(len(content), 9)
        ids = [tutorial['id'] for category in content for tutorial in category['tutorials']]
        self.assertEqual(len(ids), len(set(ids)))
        for category in content:
            self.assertContains(response, f'id="{category["id"]}"')
            for tutorial in category['tutorials']:
                self.assertContains(response, f'id="{tutorial["id"]}"')
                self.assertGreaterEqual(len(tutorial['steps']), 3)
                self.assertTrue(tutorial['example'])
                for link in tutorial['links']:
                    self.assertIn(link['id'], ids)
                    self.assertContains(response, f'href="#{link["id"]}"')
        self.assertContains(response, 'Exemplo esquemático', count=len(ids))
        video_ids = [category['video_id'] for category in content if category['video_id']]
        self.assertGreater(len(video_ids), 0)
        self.assertContains(response, 'data-video-player', count=len(video_ids))
        for video_id in set(video_ids):
            self.assertContains(response, f'data-video-id="{video_id}"', count=video_ids.count(video_id))
        self.assertNotContains(response, 'src="https://www.youtube-nocookie.com/embed/')
        self.assertContains(response, 'loading="lazy"', count=len(video_ids))
        self.assertContains(response, 'Assista ao tutorial', count=len(content))
        self.assertContains(response, 'Vídeo em breve', count=len(content) - len(video_ids))
        self.assertContains(response, 'aria-label="Tutoriais de Primeiros passos"')
        self.assertNotContains(response, 'google-analytics')
        self.assertNotContains(response, 'googletagmanager')

    def test_video_address_can_be_pasted_directly(self):
        for address in ('https://www.youtube.com/watch?v=YKfXkgw0ZNg',
                        'https://youtu.be/YKfXkgw0ZNg',
                        'https://studio.youtube.com/video/YKfXkgw0ZNg/edit'):
            with self.subTest(address=address), patch.dict(MANUAL_VIDEOS, {'profissionais': address}):
                content = categories()
                self.assertEqual(content[1]['video_id'], 'YKfXkgw0ZNg')

    def test_video_configuration_is_category_specific_and_validated(self):
        with patch.dict(MANUAL_VIDEOS, {'profissionais': 'Abc_123-xyz'}):
            configured = {category['id']: category['video_id'] for category in categories()}
        self.assertEqual(configured['profissionais'], 'Abc_123-xyz')
        self.assertEqual(configured['servicos'], MANUAL_VIDEOS['servicos'])

        with patch.dict(MANUAL_VIDEOS, {'profissionais': 'https://invalid.example/embed'}):
            configured = {category['id']: category['video_id'] for category in categories()}
        self.assertEqual(configured['profissionais'], '')
        self.assertEqual(configured['servicos'], MANUAL_VIDEOS['servicos'])


@override_settings(**PUBLIC)
class ManualSessionTests(TestCase):
    def test_authenticated_expired_owner_can_read_root_manual_without_private_data(self):
        from datetime import date
        tenant = Tenant.objects.create(nome='Nome confidencial da loja', subdomain='secreto', expira_em=date(2020, 1, 1), ativo=False)
        user = User.objects.create_user('segredo@example.test', tenant=tenant, tipo='ADMIN')
        self.client.force_login(user)
        response = self.client.get('/manual/', HTTP_HOST='tacombinado.net')
        self.assertContains(response, 'Manual do Tá Combinado')
        self.assertNotContains(response, tenant.nome)
        self.assertNotContains(response, user.email)
        self.assertIsNone(response.wsgi_request.tenant)
        # The public-document exception never opens other tenant routes.
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='tacombinado.net').status_code, 403)
