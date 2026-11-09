from unittest.mock import patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.checks import run_checks
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from agenda.models import Agendamento
from agenda.test_booking import BookingFixture
from tenants.models import Tenant
from . import turnstile

KEYS = dict(
    TURNSTILE_ENABLED=True, TURNSTILE_VERIFY_HOSTNAME=True, CLIENT_IP_HEADER='',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
            'security': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'turnstile-tests'}},
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost', 'tacombinado.net', '.tacombinado.net'],
    TURNSTILE_PUBLIC_SITE_KEY='public-site-key', TURNSTILE_PUBLIC_SECRET_KEY='public-secret-value',
    TURNSTILE_AUTH_SITE_KEY='auth-site-key', TURNSTILE_AUTH_SECRET_KEY='auth-secret-value',
)
SITEVERIFY = 'usuarios.turnstile._post_siteverify'
SECRETS = ('public-secret-value', 'auth-secret-value')
TEST_PUBLIC_SITE_KEY = '1x00000000000000000000BB'
TEST_AUTH_SITE_KEY = '1x00000000000000000000AA'
TEST_SECRET_KEY = '1x0000000000000000000000000000000AA'
TEST_TOKEN = 'XXXX.DUMMY.TOKEN.XXXX'
TEST_RESPONSE = {'success': True, 'hostname': 'example.com', 'error-codes': []}


def ok(action, hostname):
    return {'success': True, 'action': action, 'hostname': hostname, 'error-codes': []}


@override_settings(**KEYS)
class VerifyTests(SimpleTestCase):
    def setUp(self):
        caches['security'].clear()
        self.factory = RequestFactory()

    def request(self, token='token-1', host='marcos.localhost', **extra):
        data = {turnstile.RESPONSE_FIELD: token} if token is not None else {}
        remote_addr = extra.pop('REMOTE_ADDR', '203.0.113.7')
        return self.factory.post('/x/', data, HTTP_HOST=host, REMOTE_ADDR=remote_addr, **extra)

    def verify(self, request, widget=turnstile.PUBLIC, action=turnstile.ACTION_BOOKING):
        return turnstile.verify(request, widget, action)

    def test_success_sends_widget_secret_ip_and_idempotency_key(self):
        with patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')) as call:
            self.assertTrue(self.verify(self.request(host='marcos.localhost:8000')).ok)
        payload = call.call_args.args[0]
        self.assertEqual(payload['secret'], 'public-secret-value')
        self.assertEqual(payload['response'], 'token-1')
        self.assertEqual(payload['remoteip'], '203.0.113.7')
        self.assertTrue(payload['idempotency_key'])
        with patch(SITEVERIFY, return_value=ok('login', 'marcos.localhost')) as call:
            self.assertTrue(self.verify(self.request('token-2'), turnstile.AUTH, turnstile.ACTION_LOGIN).ok)
        self.assertEqual(call.call_args.args[0]['secret'], 'auth-secret-value')

    def test_missing_or_oversized_token_rejected_without_calling_cloudflare(self):
        with patch(SITEVERIFY) as call:
            self.assertFalse(self.verify(self.request(None)).ok)
            self.assertFalse(self.verify(self.request('   ')).ok)
            self.assertFalse(self.verify(self.request('x' * 2049)).ok)
        call.assert_not_called()

    def test_failed_validation_action_and_hostname_mismatch_rejected(self):
        cases = [
            {'success': False, 'error-codes': ['invalid-input-response']},
            {'success': False, 'error-codes': ['timeout-or-duplicate']},
            {'success': 'true', 'action': 'agendamento', 'hostname': 'marcos.localhost'},
            ok('login', 'marcos.localhost'),
            ok('agendamento', 'outro.localhost'),
            ok('agendamento', 'marcos.localhost.evil.test'),
            {}, [], None,
        ]
        for number, data in enumerate(cases):
            with self.subTest(data=data), patch(SITEVERIFY, return_value=data):
                result = self.verify(self.request(f'token-{number}'))
                self.assertFalse(result.ok)
                self.assertEqual(result.message, turnstile.MESSAGE_FAILED)

    def test_platform_hostnames_cover_current_and_future_tenants(self):
        with override_settings(DEBUG=False, TENANT_BASE_DOMAIN='tacombinado.net'):
            for host in ('tacombinado.net', 'marcos.tacombinado.net', 'loja-criada-amanha.tacombinado.net'):
                self.assertTrue(turnstile.is_platform_hostname(host), host)
            for host in ('', 'tacombinado.net.evil.test', 'eviltacombinado.net', 'a.b.tacombinado.net',
                         '.tacombinado.net', 'example.com', 'localhost'):
                self.assertFalse(turnstile.is_platform_hostname(host), host)

    def test_hostname_must_match_request_host_of_any_tenant(self):
        with override_settings(DEBUG=False, TENANT_BASE_DOMAIN='tacombinado.net'):
            for number, host in enumerate(('tacombinado.net', 'marcos.tacombinado.net', 'nova-loja.tacombinado.net')):
                with patch(SITEVERIFY, return_value=ok('agendamento', host.upper())):
                    self.assertTrue(self.verify(self.request(f'ok-{number}', host=host)).ok, host)
            # Token solved on another tenant of the same widget must not be accepted here.
            with patch(SITEVERIFY, return_value=ok('agendamento', 'outra.tacombinado.net')):
                self.assertFalse(self.verify(self.request('cross', host='marcos.tacombinado.net')).ok)
            with patch(SITEVERIFY, return_value=ok('agendamento', 'a.b.tacombinado.net')):
                self.assertFalse(self.verify(self.request('nested', host='a.b.tacombinado.net')).ok)

    def test_hostname_check_cannot_be_disabled_for_real_keys_in_development(self):
        with override_settings(DEBUG=True, TURNSTILE_VERIFY_HOSTNAME=False), \
                patch(SITEVERIFY, return_value=ok('agendamento', 'example.com')):
            result = self.verify(self.request())
        self.assertFalse(result.ok)
        self.assertEqual(result.errors, ('hostname-mismatch',))

    def test_hostname_check_cannot_be_disabled_in_production(self):
        with override_settings(DEBUG=False, TENANT_BASE_DOMAIN='tacombinado.net',
                               TURNSTILE_VERIFY_HOSTNAME=False), \
                patch(SITEVERIFY, return_value=ok('agendamento', 'outra.tacombinado.net')):
            result = self.verify(self.request(host='marcos.tacombinado.net'))
        self.assertFalse(result.ok)
        self.assertEqual(result.errors, ('hostname-mismatch',))

    def test_cloudflare_dummy_keys_work_repeatedly_on_localhost(self):
        with override_settings(DEBUG=True, TURNSTILE_PUBLIC_SITE_KEY=TEST_PUBLIC_SITE_KEY,
                               TURNSTILE_PUBLIC_SECRET_KEY=TEST_SECRET_KEY,
                               TURNSTILE_AUTH_SITE_KEY=TEST_AUTH_SITE_KEY,
                               TURNSTILE_AUTH_SECRET_KEY=TEST_SECRET_KEY), \
                patch(SITEVERIFY, return_value=TEST_RESPONSE) as call:
            for widget, action in (
                (turnstile.PUBLIC, turnstile.ACTION_BOOKING),
                (turnstile.AUTH, turnstile.ACTION_LOGIN),
                (turnstile.AUTH, turnstile.ACTION_REGISTRATION),
            ):
                for host in ('marcos.localhost:8000', 'nova-loja.localhost'):
                    with self.subTest(widget=widget, action=action, host=host):
                        request = self.request(TEST_TOKEN, host=host, REMOTE_ADDR='127.0.0.1')
                        self.assertTrue(self.verify(request, widget, action).ok)
        self.assertEqual(call.call_count, 6)

    def test_dummy_response_requires_success_and_expected_shape(self):
        cases = [
            {'success': False, 'error-codes': ['invalid-input-response']},
            {'success': True, 'hostname': 'outro.localhost', 'error-codes': []},
            {'success': True, 'hostname': 'example.com', 'action': 'login', 'error-codes': []},
            {'success': True, 'hostname': 'example.com', 'error-codes': ['internal-error']},
            {},
        ]
        with override_settings(DEBUG=True, TURNSTILE_PUBLIC_SITE_KEY=TEST_PUBLIC_SITE_KEY,
                               TURNSTILE_PUBLIC_SECRET_KEY=TEST_SECRET_KEY):
            for response in cases:
                with self.subTest(response=response), patch(SITEVERIFY, return_value=response) as call:
                    request = self.request(TEST_TOKEN, REMOTE_ADDR='127.0.0.1')
                    self.assertFalse(self.verify(request).ok)
                    call.assert_called_once()

    def test_dummy_verification_still_fails_when_siteverify_is_unavailable(self):
        with override_settings(DEBUG=True, TURNSTILE_PUBLIC_SITE_KEY=TEST_PUBLIC_SITE_KEY,
                               TURNSTILE_PUBLIC_SECRET_KEY=TEST_SECRET_KEY), \
                patch(SITEVERIFY, side_effect=URLError('down')):
            result = self.verify(self.request(TEST_TOKEN, REMOTE_ADDR='127.0.0.1'))
        self.assertFalse(result.ok)
        self.assertEqual(result.message, turnstile.MESSAGE_UNAVAILABLE)

    def test_dummy_keys_do_not_bypass_remote_or_production_verification(self):
        cases = [
            {'DEBUG': True, 'host': 'marcos.localhost', 'remote': '203.0.113.7'},
            {'DEBUG': True, 'host': 'marcos.tacombinado.net', 'remote': '127.0.0.1'},
            {'DEBUG': False, 'host': 'marcos.localhost', 'remote': '127.0.0.1'},
        ]
        for case in cases:
            caches['security'].clear()
            with self.subTest(case=case), \
                    override_settings(DEBUG=case['DEBUG'], TURNSTILE_PUBLIC_SITE_KEY=TEST_PUBLIC_SITE_KEY,
                                      TURNSTILE_PUBLIC_SECRET_KEY=TEST_SECRET_KEY), \
                    patch(SITEVERIFY, return_value=TEST_RESPONSE):
                request = self.request(TEST_TOKEN, host=case['host'], REMOTE_ADDR=case['remote'])
                self.assertFalse(self.verify(request).ok)

    def test_dummy_token_does_not_bypass_real_keys(self):
        with override_settings(DEBUG=True), patch(SITEVERIFY, return_value=TEST_RESPONSE):
            request = self.request(TEST_TOKEN, REMOTE_ADDR='127.0.0.1')
            self.assertFalse(self.verify(request).ok)

    def test_production_rejects_either_test_key_before_calling_siteverify(self):
        cases = [
            (TEST_PUBLIC_SITE_KEY, 'public-secret-value'),
            ('public-site-key', TEST_SECRET_KEY),
        ]
        for site_key, secret in cases:
            with self.subTest(site_key=site_key), \
                    override_settings(DEBUG=False, TURNSTILE_PUBLIC_SITE_KEY=site_key,
                                      TURNSTILE_PUBLIC_SECRET_KEY=secret), \
                    patch(SITEVERIFY) as call:
                result = self.verify(self.request(TEST_TOKEN))
                self.assertEqual(result.errors, ('invalid-test-key-configuration',))
                self.assertEqual(result.message, turnstile.MESSAGE_UNAVAILABLE)
                call.assert_not_called()

    def test_dummy_exception_requires_both_test_keys_and_the_exact_dummy_token(self):
        cases = [
            (TEST_PUBLIC_SITE_KEY, 'public-secret-value', TEST_TOKEN),
            ('public-site-key', TEST_SECRET_KEY, TEST_TOKEN),
            (TEST_PUBLIC_SITE_KEY, TEST_SECRET_KEY, 'another-token'),
        ]
        for site_key, secret, token in cases:
            caches['security'].clear()
            with self.subTest(site_key=site_key, token=token), \
                    override_settings(DEBUG=True, TURNSTILE_PUBLIC_SITE_KEY=site_key,
                                      TURNSTILE_PUBLIC_SECRET_KEY=secret), \
                    patch(SITEVERIFY, return_value=TEST_RESPONSE) as call:
                request = self.request(token, REMOTE_ADDR='127.0.0.1')
                self.assertFalse(self.verify(request).ok)
                call.assert_called_once()

    def test_real_tokens_remain_single_use_in_local_development(self):
        with override_settings(DEBUG=True), \
                patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')) as call:
            request = self.request('real-token', REMOTE_ADDR='127.0.0.1')
            self.assertTrue(self.verify(request).ok)
            self.assertFalse(self.verify(request).ok)
        call.assert_called_once()

    def test_communication_failures_never_succeed(self):
        for number, error in enumerate([URLError('down'), TimeoutError(), OSError(), ValueError('json')]):
            with self.subTest(error=error), patch(SITEVERIFY, side_effect=error):
                result = self.verify(self.request(f'token-{number}'))
                self.assertFalse(result.ok)
                self.assertEqual(result.errors, ('internal-error',))
                self.assertEqual(result.message, turnstile.MESSAGE_UNAVAILABLE)

    def test_reused_token_rejected_locally(self):
        with patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')) as call:
            self.assertTrue(self.verify(self.request('same')).ok)
            self.assertFalse(self.verify(self.request('same')).ok)
        self.assertEqual(call.call_count, 1)

    def test_missing_secret_fails_closed(self):
        with override_settings(TURNSTILE_PUBLIC_SECRET_KEY=''), patch(SITEVERIFY) as call:
            result = self.verify(self.request())
        self.assertFalse(result.ok)
        self.assertEqual(result.message, turnstile.MESSAGE_UNAVAILABLE)
        call.assert_not_called()

    def test_disabled_skips_verification(self):
        with override_settings(TURNSTILE_ENABLED=False), patch(SITEVERIFY) as call:
            self.assertTrue(self.verify(self.request(None)).ok)
            self.assertIsNone(turnstile.widget_context(turnstile.PUBLIC, turnstile.ACTION_BOOKING))
        call.assert_not_called()

    def test_turnstile_cannot_be_disabled_in_production(self):
        with override_settings(DEBUG=False, RUNNING_TESTS=False, TURNSTILE_ENABLED=False), \
                patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')) as call:
            self.assertFalse(self.verify(self.request(None)).ok)
            self.assertTrue(self.verify(self.request('valid-token')).ok)
            self.assertIsNotNone(turnstile.widget_context(turnstile.PUBLIC, turnstile.ACTION_BOOKING))
        call.assert_called_once()

    def test_widget_context_never_contains_secret(self):
        context = turnstile.widget_context(turnstile.AUTH, turnstile.ACTION_LOGIN)
        self.assertEqual(context['site_key'], 'auth-site-key')
        self.assertNotIn('auth-secret-value', str(context))

    def test_client_ip_header_only_when_configured_and_valid(self):
        request = self.request(HTTP_CF_CONNECTING_IP='198.51.100.9')
        self.assertEqual(turnstile.client_ip(request), '203.0.113.7')
        with override_settings(CLIENT_IP_HEADER='CF-Connecting-IP'):
            self.assertEqual(turnstile.client_ip(request), '198.51.100.9')
            self.assertEqual(turnstile.client_ip(self.request(HTTP_CF_CONNECTING_IP='forged')), '203.0.113.7')

    def test_system_check_reports_missing_keys_when_enabled(self):
        with override_settings(TURNSTILE_AUTH_SECRET_KEY=''):
            errors = [e for e in run_checks() if e.id == 'usuarios.E001']
        self.assertEqual(len(errors), 1)
        self.assertIn('TURNSTILE_AUTH_SECRET_KEY', errors[0].msg)
        self.assertNotIn('public-secret-value', errors[0].msg)
        self.assertFalse([e for e in run_checks() if e.id == 'usuarios.E001'])

    def test_system_check_rejects_dummy_keys_in_production(self):
        with override_settings(DEBUG=False, TURNSTILE_PUBLIC_SITE_KEY=TEST_PUBLIC_SITE_KEY,
                               TURNSTILE_PUBLIC_SECRET_KEY=TEST_SECRET_KEY):
            errors = [e for e in run_checks() if e.id == 'usuarios.E002']
        self.assertEqual(len(errors), 1)
        self.assertIn('TURNSTILE_PUBLIC_SITE_KEY', errors[0].msg)
        self.assertIn('TURNSTILE_PUBLIC_SECRET_KEY', errors[0].msg)
        self.assertNotIn(TEST_SECRET_KEY, errors[0].msg)

    def test_system_check_rejects_disabling_hostname_verification_in_production(self):
        with override_settings(DEBUG=False, TURNSTILE_VERIFY_HOSTNAME=False):
            errors = [e for e in run_checks() if e.id == 'usuarios.E003']
        self.assertEqual(len(errors), 1)

    def test_system_check_warns_when_hostname_flag_is_disabled_in_development(self):
        with override_settings(DEBUG=True, TURNSTILE_VERIFY_HOSTNAME=False):
            warnings = [e for e in run_checks() if e.id == 'usuarios.W001']
        self.assertEqual(len(warnings), 1)

    def test_system_check_rejects_disabling_turnstile_in_production(self):
        with override_settings(DEBUG=False, RUNNING_TESTS=False, TURNSTILE_ENABLED=False):
            errors = [e for e in run_checks() if e.id == 'usuarios.E004']
        self.assertEqual(len(errors), 1)


class SecurityCacheMixin:
    def setUp(self):
        caches['security'].clear()
        super().setUp()

    def assertNoSecrets(self, response):
        for secret in SECRETS:
            self.assertNotContains(response, secret)


@override_settings(**KEYS)
class PublicBookingTurnstileTests(SecurityCacheMixin, BookingFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.setup_booking()
        self.host = {'HTTP_HOST': 'marcos.localhost'}

    def post(self, token='booking-token', **kwargs):
        data = self.payload(**kwargs)
        if token:
            data[turnstile.RESPONSE_FIELD] = token
        return self.client.post(self.slots_url(), data, **self.host)

    def test_page_renders_invisible_widget_with_public_site_key_only(self):
        page = self.client.get(self.slots_url(), **self.host)
        self.assertContains(page, 'data-sitekey="public-site-key"')
        self.assertContains(page, 'data-action="agendamento"')
        self.assertContains(page, 'render=explicit')
        self.assertContains(page, 'turnstile-agendamento.js')
        self.assertNotContains(page, 'auth-site-key')
        self.assertContains(page, 'name="nome"')
        self.assertContains(page, 'name="whatsapp"')
        self.assertNoSecrets(page)

    def test_booking_requires_valid_token(self):
        with patch(SITEVERIFY) as call:
            response = self.post(token='')
        call.assert_not_called()
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, turnstile.MESSAGE_FAILED, status_code=403)
        self.assertFalse(Agendamento.objects.exists())

    def test_booking_with_valid_token_is_created(self):
        with patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')):
            response = self.post()
        self.assertEqual(response.status_code, 302)
        booking = Agendamento.objects.get()
        self.assertEqual(booking.tenant_id, self.tenant.pk)
        self.assertEqual(booking.whatsapp_contato, '+5511999991234')

    def test_two_local_bookings_can_use_cloudflare_dummy_token(self):
        with override_settings(DEBUG=True, TURNSTILE_PUBLIC_SITE_KEY=TEST_PUBLIC_SITE_KEY,
                               TURNSTILE_PUBLIC_SECRET_KEY=TEST_SECRET_KEY), \
                patch(SITEVERIFY, return_value=TEST_RESPONSE) as call:
            first = self.post(token=TEST_TOKEN)
            second = self.post(token=TEST_TOKEN, hora='09:47', whatsapp='(11) 99999-5678')
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Agendamento.objects.count(), 2)
        self.assertEqual(call.call_count, 2)

    def test_wrong_action_other_tenant_hostname_reuse_and_outage_rejected(self):
        cases = [
            ('t1', {'return_value': ok('login', 'marcos.localhost')}),
            ('t2', {'return_value': ok('agendamento', 'wanessa.localhost')}),
            ('t3', {'side_effect': URLError('down')}),
        ]
        for token, mock in cases:
            with self.subTest(token=token), patch(SITEVERIFY, **mock):
                self.assertEqual(self.post(token=token).status_code, 403)
        self.assertFalse(Agendamento.objects.exists())
        with patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')):
            self.assertEqual(self.post(token='once').status_code, 302)
            self.assertEqual(self.post(token='once', hora='09:47').status_code, 403)
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_business_validation_still_applies_after_turnstile(self):
        with patch(SITEVERIFY, return_value=ok('agendamento', 'marcos.localhost')):
            response = self.post(hora='08:00')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Agendamento.objects.exists())


@override_settings(**KEYS, LOGIN_RATE_LIMIT_PER_IP=6, LOGIN_RATE_LIMIT_PER_EMAIL=3, AUTH_RATE_LIMIT_WINDOW_SECONDS=900)
class LoginTurnstileTests(SecurityCacheMixin, TestCase):
    password = 'Painel!Senha2026'

    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos', plano=Tenant.Plano.PROFISSIONAL)
        self.user = get_user_model().objects.create_user(
            'admin@example.test', self.password, tenant=self.tenant, tipo='ADMIN')
        self.host = {'HTTP_HOST': 'marcos.localhost', 'REMOTE_ADDR': '203.0.113.20'}

    def post(self, password=None, token='login-token', email='admin@example.test', **extra):
        data = {'email': email, 'password': password or self.password}
        if token:
            data[turnstile.RESPONSE_FIELD] = token
        return self.client.post('/login/', data, **{**self.host, **extra})

    def test_page_renders_managed_widget(self):
        page = self.client.get('/login/', **self.host)
        self.assertContains(page, 'class="cf-turnstile turnstile-auth"')
        self.assertContains(page, 'data-sitekey="auth-site-key"')
        self.assertContains(page, 'data-action="login"')
        self.assertContains(page, turnstile.SCRIPT_URL)
        self.assertNoSecrets(page)

    def test_newly_created_tenant_is_protected_without_configuration(self):
        novo = Tenant.objects.create(nome='Recém-criado', subdomain='recemcriado')
        admin = get_user_model().objects.create_user('novo@example.test', self.password, tenant=novo, tipo='ADMIN')
        host = {'HTTP_HOST': 'recemcriado.localhost', 'REMOTE_ADDR': '203.0.113.40'}
        page = self.client.get('/login/', **host)
        self.assertContains(page, 'data-sitekey="auth-site-key"')
        data = {'email': admin.email, 'password': self.password}
        self.assertEqual(self.client.post('/login/', data, **host).status_code, 400)
        with patch(SITEVERIFY, return_value=ok('login', 'recemcriado.localhost')):
            data[turnstile.RESPONSE_FIELD] = 'novo-token'
            self.assertEqual(self.client.post('/login/', data, **host).status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), admin.pk)

    def test_login_requires_token_before_authenticating(self):
        with patch(SITEVERIFY) as call, patch('usuarios.forms.authenticate') as auth:
            response = self.post(token='')
        call.assert_not_called()
        auth.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertNotContains(response, self.password, status_code=400)

    def test_login_with_valid_token(self):
        with patch(SITEVERIFY, return_value=ok('login', 'marcos.localhost')):
            response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_registration_token_cannot_be_used_for_login(self):
        with patch(SITEVERIFY, return_value=ok('cadastro', 'marcos.localhost')):
            self.assertEqual(self.post().status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_failed_logins_limited_per_email(self):
        with patch(SITEVERIFY, side_effect=lambda payload: ok('login', 'marcos.localhost')):
            for number in range(3):
                self.assertEqual(self.post('errada', token=f'e{number}').status_code, 200)
            with patch('usuarios.forms.authenticate') as auth:
                response = self.post(token='e-final', REMOTE_ADDR='203.0.113.99')
            auth.assert_not_called()
        self.assertEqual(response.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_successful_login_resets_email_counter(self):
        with patch(SITEVERIFY, side_effect=lambda payload: ok('login', 'marcos.localhost')):
            for number in range(2):
                self.post('errada', token=f'e{number}')
            self.assertEqual(self.post(token='good').status_code, 302)
            self.client.logout()
            for number in range(2):
                self.assertEqual(self.post('errada', token=f'f{number}').status_code, 200)

    def test_attempts_limited_per_ip_including_turnstile_failures(self):
        with patch(SITEVERIFY, return_value={'success': False, 'error-codes': ['invalid-input-response']}) as call:
            for number in range(6):
                self.assertEqual(self.post(token=f'bad{number}', email=f'u{number}@example.test').status_code, 400)
            self.assertEqual(self.post(token='bad-last', email='other@example.test').status_code, 429)
        self.assertEqual(call.call_count, 6)
        with patch(SITEVERIFY, return_value=ok('login', 'marcos.localhost')):
            self.assertEqual(self.post(token='other-ip', REMOTE_ADDR='203.0.113.21').status_code, 302)


@override_settings(**KEYS, REGISTRATION_RATE_LIMIT_PER_IP=2)
class RegistrationTurnstileTests(SecurityCacheMixin, TestCase):
    host = {'HTTP_HOST': 'localhost', 'REMOTE_ADDR': '203.0.113.30'}

    def data(self, number=1, token='reg-token'):
        data = {'subdomain': f'novo{number}', 'email': f'novo{number}@example.test',
                'password1': 'Cadastro!Seguro2026', 'password2': 'Cadastro!Seguro2026'}
        if token:
            data[turnstile.RESPONSE_FIELD] = f'{token}-{number}'
        return data

    def test_page_renders_managed_widget(self):
        page = self.client.get('/registro/', **self.host)
        self.assertContains(page, 'data-sitekey="auth-site-key"')
        self.assertContains(page, 'data-action="cadastro"')
        self.assertNoSecrets(page)

    def test_registration_requires_valid_token(self):
        with patch(SITEVERIFY) as call:
            response = self.client.post('/registro/', self.data(token=''), **self.host)
        call.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Tenant.objects.exists())
        self.assertNotContains(response, 'Cadastro!Seguro2026', status_code=400)
        with patch(SITEVERIFY, return_value=ok('login', 'localhost')):
            self.assertEqual(self.client.post('/registro/', self.data(), **self.host).status_code, 400)
        self.assertFalse(Tenant.objects.exists())

    def test_registration_with_valid_token(self):
        with patch(SITEVERIFY, return_value=ok('cadastro', 'localhost')):
            response = self.client.post('/registro/', self.data(), **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Tenant.objects.filter(subdomain='novo1').exists())

    def test_registration_rate_limited_per_ip(self):
        with patch(SITEVERIFY, side_effect=lambda payload: ok('cadastro', 'localhost')) as call:
            for number in range(2):
                self.client.post('/registro/', self.data(number), **self.host)
            response = self.client.post('/registro/', self.data(9), **self.host)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(call.call_count, 2)
        self.assertFalse(Tenant.objects.filter(subdomain='novo9').exists())


@override_settings(**KEYS)
class PrivacyPolicyTurnstileTests(TestCase):
    def test_policy_public_on_any_host_without_widget(self):
        for host in ('localhost', 'marcos.localhost', 'inexistente.localhost'):
            with self.subTest(host=host):
                page = self.client.get('/politica-de-privacidade/', HTTP_HOST=host)
                self.assertContains(page, 'https://www.cloudflare.com/en-gb/turnstile-privacy-policy/')
                self.assertContains(page, 'target="_blank"')
                self.assertNotContains(page, 'cf-turnstile')
                self.assertNotContains(page, turnstile.SCRIPT_URL)
