"""Cloudflare Turnstile server-side validation (Siteverify).

Every failure path (missing keys, network errors, unexpected payloads) is treated
as a rejected verification. Secret keys never leave this module.
"""
import hashlib
import ipaddress
import json
import logging
import uuid
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import caches
from django.http.request import split_domain_port

from tenants.domains import tenant_base_domain_for_host

logger = logging.getLogger(__name__)

SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
RESPONSE_FIELD = 'cf-turnstile-response'
MAX_TOKEN_LENGTH = 2048
TOKEN_TTL_SECONDS = 300

# Cloudflare's documented dummy keys and token do not represent real credentials.
TEST_SITE_KEYS = frozenset({
    '1x00000000000000000000AA', '1x00000000000000000000BB',
    '2x00000000000000000000AB', '2x00000000000000000000BB',
    '3x00000000000000000000FF',
})
TEST_SECRET_KEYS = frozenset({
    '1x0000000000000000000000000000000AA',
    '2x0000000000000000000000000000000AA',
    '3x0000000000000000000000000000000AA',
})
TEST_TOKEN = 'XXXX.DUMMY.TOKEN.XXXX'
TEST_HOSTNAME = 'example.com'

PUBLIC = 'public'
AUTH = 'auth'
ACTION_BOOKING = 'agendamento'
ACTION_LOGIN = 'login'
ACTION_REGISTRATION = 'cadastro'

MESSAGE_FAILED = 'Não foi possível confirmar a verificação de segurança. Tente novamente.'
MESSAGE_UNAVAILABLE = 'A verificação de segurança está temporariamente indisponível. Tente novamente em instantes.'


@dataclass(frozen=True)
class Result:
    ok: bool
    errors: tuple = field(default_factory=tuple)

    @property
    def message(self):
        if self.ok:
            return ''
        if {'internal-error', 'missing-input-secret', 'invalid-input-secret',
                'invalid-test-key-configuration'} & set(self.errors):
            return MESSAGE_UNAVAILABLE
        return MESSAGE_FAILED


def enabled():
    return settings.TURNSTILE_ENABLED or (not settings.DEBUG and not settings.RUNNING_TESTS)


def _keys(widget):
    if widget == PUBLIC:
        return settings.TURNSTILE_PUBLIC_SITE_KEY, settings.TURNSTILE_PUBLIC_SECRET_KEY
    if widget == AUTH:
        return settings.TURNSTILE_AUTH_SITE_KEY, settings.TURNSTILE_AUTH_SECRET_KEY
    raise ValueError(f'Widget Turnstile desconhecido: {widget}')


def widget_context(widget, action):
    """Public data needed by templates; never includes the secret key."""
    if not enabled():
        return None
    site_key, _ = _keys(widget)
    return {'site_key': site_key, 'action': action, 'script_url': SCRIPT_URL, 'field': RESPONSE_FIELD}


def client_ip(request):
    header = settings.CLIENT_IP_HEADER
    candidates = []
    if header:
        candidates.append(request.headers.get(header, '').split(',')[0].strip())
    candidates.append(request.META.get('REMOTE_ADDR', ''))
    for value in candidates:
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue
    return ''


def _request_hostname(request):
    host, _ = split_domain_port(request.get_host())
    return host.lower()


def is_platform_hostname(hostname):
    """Base domain or a single-label subdomain of it: covers current and future tenants
    without per-tenant configuration (one Cloudflare hostname entry covers all subdomains)."""
    hostname = (hostname or '').lower()
    base = tenant_base_domain_for_host(hostname)
    if not hostname or not base:
        return False
    if hostname == base:
        return True
    label = hostname[:-len(base) - 1] if hostname.endswith('.' + base) else ''
    return bool(label) and '.' not in label


def hostname_matches(request, hostname):
    expected = _request_hostname(request)
    return str(hostname or '').lower() == expected and is_platform_hostname(expected)


def _is_local_dummy_verification(request, site_key, secret, token):
    if not settings.DEBUG or site_key not in TEST_SITE_KEYS or secret not in TEST_SECRET_KEYS or token != TEST_TOKEN:
        return False
    hostname = _request_hostname(request)
    if hostname not in {'localhost', '127.0.0.1', '[::1]'} and not (
        hostname.endswith('.localhost') and is_platform_hostname(hostname)
    ):
        return False
    try:
        return ipaddress.ip_address(request.META.get('REMOTE_ADDR', '')).is_loopback
    except ValueError:
        return False


def _post_siteverify(payload):
    body = urlencode(payload).encode()
    http_request = Request(SITEVERIFY_URL, data=body, method='POST',
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urlopen(http_request, timeout=settings.TURNSTILE_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise URLError(f'HTTP {response.status}')
        return json.loads(response.read(65536).decode('utf-8'))


def _fail(widget, action, *errors):
    logger.warning('Turnstile rejeitado (widget=%s, action=%s): %s', widget, action, ', '.join(errors))
    return Result(False, tuple(errors))


def verify(request, widget, action):
    if not enabled():
        return Result(True)
    site_key, secret = _keys(widget)
    if not settings.DEBUG and (site_key in TEST_SITE_KEYS or secret in TEST_SECRET_KEYS):
        logger.error('Chaves de teste do Turnstile não são permitidas em produção (widget=%s).', widget)
        return _fail(widget, action, 'invalid-test-key-configuration')
    if not secret:
        logger.error('Turnstile ativo sem chave secreta configurada para o widget %s.', widget)
        return _fail(widget, action, 'missing-input-secret')
    token = request.POST.get(RESPONSE_FIELD, '').strip()
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return _fail(widget, action, 'missing-input-response')

    local_dummy = _is_local_dummy_verification(request, site_key, secret, token)
    if not local_dummy:
        # Real tokens are single-use; Cloudflare's local dummy token is always the same.
        used_key = 'turnstile:used:' + hashlib.sha256(token.encode()).hexdigest()
        if not caches['security'].add(used_key, 1, TOKEN_TTL_SECONDS):
            return _fail(widget, action, 'timeout-or-duplicate')

    payload = {'secret': secret, 'response': token, 'idempotency_key': str(uuid.uuid4())}
    ip = client_ip(request)
    if ip:
        payload['remoteip'] = ip
    try:
        data = _post_siteverify(payload)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        logger.error('Falha de comunicação com o Turnstile Siteverify: %s', exc.__class__.__name__)
        return _fail(widget, action, 'internal-error')

    if not isinstance(data, dict) or data.get('success') is not True:
        errors = data.get('error-codes') if isinstance(data, dict) else None
        valid = isinstance(errors, list) and all(isinstance(code, str) for code in errors)
        return _fail(widget, action, *(errors if valid and errors else ['verification-failed']))
    if local_dummy:
        # Siteverify's dummy response omits action and uses the fixed hostname example.com.
        if data.get('hostname') != TEST_HOSTNAME or 'action' in data or data.get('error-codes', []) != []:
            return _fail(widget, action, 'test-response-mismatch')
        return Result(True)
    if data.get('action') != action:
        return _fail(widget, action, 'action-mismatch')
    if not hostname_matches(request, data.get('hostname')):
        return _fail(widget, action, 'hostname-mismatch')
    return Result(True)
