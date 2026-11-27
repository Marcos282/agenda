import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from django.db import close_old_connections, connection
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tenants.logo_generation import GenerationError, claim_job, enqueue, generate_image, process_job, validate_image
from tenants.models import LogoAccount, LogoGeneration, LogoSettings, Tenant, TenantTheme
from usuarios.models import User


def png_bytes(*, transparent=True):
    image = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0 if transparent else 255))
    image.paste((40, 116, 84, 255), (400, 400, 624, 624))
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class OpenAIImageTests(SimpleTestCase):
    @patch('tenants.logo_generation.http.client.HTTPSConnection')
    @patch('tenants.logo_generation.dotenv_values', return_value={'OPENAI_API_KEY': 'test-only'})
    def test_official_request_validates_and_reencodes_logo(self, secret, https):
        import json
        api = https.return_value
        response = api.getresponse.return_value
        response.status = 200
        response.getheader.return_value = 'req_test'
        response.read.return_value = json.dumps({
            'data': [{'b64_json': base64.b64encode(png_bytes()).decode()}],
            'usage': {'total_tokens': 120, 'input_tokens': 20, 'output_tokens': 100, 'private': 'ignored'},
        }).encode()
        job = LogoGeneration(brief={'name': 'Salão Único'}, model_name='gpt-image-2.5-flare')
        logo, provider_id, usage = generate_image(job)
        path = api.request.call_args.args[1]
        payload = json.loads(api.request.call_args.kwargs['body'])
        self.assertEqual(path, '/v1/images/generations')
        self.assertEqual((payload['background'], payload['size'], payload['output_format']),
                         ('transparent', '1024x1024', 'png'))
        self.assertIn('Salão Único', payload['prompt'])
        self.assertEqual((provider_id, usage['total_tokens']), ('req_test', 120))
        self.assertNotIn('private', usage)
        with Image.open(logo) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertEqual(image.getchannel('A').getextrema(), (0, 255))

    def test_rejects_opaque_output(self):
        with self.assertRaises(ValueError):
            validate_image(base64.b64encode(png_bytes(transparent=False)))


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost'], DEV_PUBLIC_HOST='',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LogoPanelTests(TestCase):
    def setUp(self):
        LogoSettings.objects.update_or_create(pk=1, defaults={'enabled': True})
        self.tenant = Tenant.objects.create(nome='Salão Único', subdomain='salao')
        self.host = {'HTTP_HOST': 'salao.localhost'}
        self.admin = User.objects.create_user('admin@example.test', 'unused', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.brief = {
            'name': self.tenant.nome, 'segment': 'Salão', 'style': 'modern',
            'primary_color': '#287454', 'secondary_color': '#ffffff', 'request_id': str(uuid4()),
        }
        storage = LogoGeneration._meta.get_field('image').storage
        files = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(storage, 'location', files))

    def request_logo(self, **overrides):
        return self.client.post(reverse('painel:logo_generate'), {**self.brief, **overrides}, **self.host)

    def balance(self):
        return LogoAccount.objects.get(tenant=self.tenant).credits

    def test_success_charges_once_and_requires_confirmation(self):
        old = TenantTheme.objects.create(tenant=self.tenant, logo_image=f'tenants/{self.tenant.pk}/original.webp')
        self.assertEqual(self.request_logo().status_code, 200)
        self.assertEqual(self.request_logo().status_code, 200)
        self.assertEqual(LogoGeneration.objects.count(), 1)
        self.assertEqual(self.balance(), 3)
        self.assertEqual(self.request_logo(request_id=uuid4()).status_code, 409)

        job_id = claim_job()
        logo = validate_image(base64.b64encode(png_bytes()))
        with patch('tenants.logo_generation.generate_image', return_value=(logo, 'req_test', {'total_tokens': 120})) as api:
            process_job(job_id)
            process_job(job_id)
        api.assert_called_once()
        self.assertEqual(self.balance(), 2)
        self.assertEqual(TenantTheme.objects.get(pk=old.pk).logo_image.name, old.logo_image.name)

        status = self.client.get(reverse('painel:logo_status', args=[job_id]), **self.host).json()
        self.assertEqual(status['credits'], 2)
        download = self.client.get(status['download_url'], **self.host)
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment', download['Content-Disposition'])
        self.assertTrue(b''.join(download.streaming_content).startswith(b'RIFF'))
        for _ in range(2):
            self.assertEqual(self.client.post(status['apply_url'], **self.host).status_code, 302)
        self.assertEqual(self.balance(), 2)
        self.assertEqual(TenantTheme.objects.get(pk=old.pk).logo_image.name,
                         LogoGeneration.objects.get(pk=job_id).image.name)
        self.assertContains(self.client.get(reverse('painel:logo_history'), **self.host), 'Baixar imagem')
        self.assertEqual(self.request_logo(request_id=uuid4()).status_code, 429)

    def test_provider_failure_abandoned_worker_and_exhausted_credits(self):
        self.request_logo()
        job_id = claim_job()
        with patch('tenants.logo_generation.generate_image', side_effect=GenerationError('http_429', 'req_rate')):
            process_job(job_id)
        job = LogoGeneration.objects.get(pk=job_id)
        self.assertEqual((job.status, job.error_code, job.provider_request_id), ('failed', 'http_429', 'req_rate'))
        self.assertEqual(self.balance(), 3)

        LogoGeneration.objects.filter(pk=job_id).update(status='running',
                                                       started_at=timezone.now() - timedelta(minutes=6))
        self.assertIsNone(claim_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ('failed', 'worker_interrupted'))
        self.assertEqual(self.balance(), 3)

        LogoAccount.objects.filter(tenant=self.tenant).update(credits=0)
        self.assertEqual(self.request_logo(request_id=uuid4()).status_code, 409)

    def test_permissions_isolation_and_csrf(self):
        other = Tenant.objects.create(nome='Outro', subdomain='outro')
        other_job = LogoGeneration.objects.create(tenant=other, request_id=uuid4(), status='ready')
        for endpoint in ('logo_status', 'logo_image', 'logo_download', 'logo_apply'):
            method = self.client.post if endpoint == 'logo_apply' else self.client.get
            self.assertEqual(method(reverse(f'painel:{endpoint}', args=[other_job.pk]), **self.host).status_code, 404)
        self.assertNotContains(self.client.get(reverse('painel:logo_history'), **self.host), str(other_job.pk))
        self.assertEqual(self.client.post(reverse('painel:logo_generate'), self.brief,
                                          HTTP_HOST='outro.localhost').status_code, 403)

        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.admin)
        self.assertEqual(secured.post(reverse('painel:logo_generate'), self.brief, **self.host).status_code, 403)
        viewer = User.objects.create_user('profissional@example.test', 'unused', tenant=self.tenant, tipo='PROFISSIONAL')
        self.client.force_login(viewer)
        self.assertEqual(self.request_logo().status_code, 403)
        self.client.logout()
        self.assertEqual(self.request_logo().status_code, 302)

    def test_global_tenant_flags_and_new_tenant_balance(self):
        LogoSettings.objects.filter(pk=1).update(initial_credits=7, enabled=False)
        self.assertEqual(self.request_logo().status_code, 403)
        LogoSettings.objects.filter(pk=1).update(enabled=True)
        LogoAccount.objects.filter(tenant=self.tenant).update(enabled=False)
        self.assertEqual(self.request_logo().status_code, 403)
        self.assertEqual(self.balance(), 3)
        new_tenant = Tenant.objects.create(nome='Novo', subdomain='novo')
        self.assertEqual(new_tenant.logo_account.credits, 7)

    def test_platform_admin_can_adjust_credits_without_overwriting_balance(self):
        account = self.tenant.logo_account
        platform_admin = User.objects.create_superuser('platform@example.test', 'unused')
        admin = Client()
        admin.force_login(platform_admin)
        url = reverse('admin:tenants_logoaccount_change', args=[account.pk])
        dashboard = {'HTTP_HOST': 'localhost'}
        self.assertContains(admin.get(url, **dashboard), 'Ajuste de créditos')
        self.assertEqual(admin.post(url, {'enabled': 'on', 'credit_adjustment': '2'}, **dashboard).status_code, 302)
        self.assertEqual(self.balance(), 5)
        self.request_logo()
        response = admin.post(url, {'enabled': 'on', 'credit_adjustment': '-5'}, **dashboard)
        self.assertContains(response, 'Mantenha um crédito disponível')
        self.assertEqual(self.balance(), 5)
        self.assertEqual(admin.post(url, {'enabled': 'on', 'credit_adjustment': '-4'}, **dashboard).status_code, 302)
        self.assertEqual(self.balance(), 1)


class LogoConcurrencyTests(TransactionTestCase):
    def test_simultaneous_requests_create_only_one_job(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requer bloqueios de linha do PostgreSQL.')
        LogoSettings.objects.update_or_create(pk=1, defaults={'enabled': True})
        tenant = Tenant.objects.create(nome='Concorrência', subdomain='concorrencia')
        barrier = Barrier(2, timeout=5)

        def send():
            close_old_connections()
            try:
                barrier.wait()
                return enqueue(tenant, uuid4(), {})[1]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: send(), range(2)))
        self.assertCountEqual(outcomes, ['', 'busy'])
        self.assertEqual(LogoGeneration.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(LogoAccount.objects.get(tenant=tenant).credits, 3)
