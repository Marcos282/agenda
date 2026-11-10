"""Idempotent webhook setup shared by the connection panel and maintenance CLI."""
from urllib.parse import urlsplit

from django.conf import settings
from django.http.request import split_domain_port
from . import evolution
from .reply_views import webhook_token


class WebhookSetupError(evolution.EvolutionError):
    pass


def ensure_webhook(tenant, *, apply=True, request=None):
    host = f'{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}'
    # Never point a local test instance at a production callback inadvertently.
    # Callback routing depends on the tenant host, so a localhost/tunnel URL
    # cannot be substituted without explicitly supporting that environment.
    if request is not None and split_domain_port(request.get_host().lower())[0] != host:
        raise WebhookSetupError('O recebimento automático precisa ser configurado no endereço público deste estabelecimento.')
    name = evolution.instance(tenant)
    target = f'https://{host}/whatsapp/respostas/'
    current = evolution.request('GET', '/webhook/find/' + name) or {}
    if not isinstance(current, dict):
        raise WebhookSetupError('Não foi possível conferir a configuração de recebimento.')
    previous = current.get('url') or ''
    if not isinstance(previous, str):
        raise WebhookSetupError('Não foi possível conferir a configuração de recebimento.')
    if previous:
        parts = urlsplit(previous)
        if parts.scheme != 'https' or parts.netloc != host or parts.path.rstrip('/') not in {
                '/whatsapp/respostas', '/teste/receber', '/testes/whatsapp/receber'} or parts.query or parts.fragment:
            raise WebhookSetupError('Já existe webhook de outra integração. Ele foi preservado; solicite ajuda ao suporte.')
        target = previous
    events = current.get('events') or []
    headers = current.get('headers') or {}
    if (not isinstance(events, list) or any(not isinstance(event, str) for event in events)
            or not isinstance(headers, dict) or any(not isinstance(key, str) for key in headers)):
        raise WebhookSetupError('Não foi possível conferir a configuração de recebimento.')
    if not apply:
        return False
    required_headers = {'X-Agendamento-Token': webhook_token(tenant)}
    if urlsplit(target).path.rstrip('/') != '/whatsapp/respostas':
        from .inbox_views import webhook_token as inbox_token
        required_headers['X-TestZap-Token'] = inbox_token(tenant)

    def matches(data):
        if (not isinstance(data, dict) or not isinstance(data.get('headers'), dict)
                or any(not isinstance(key, str) for key in data['headers'])):
            return False
        actual_headers = {key.lower(): value for key, value in data['headers'].items()}
        return (data.get('enabled') is True and data.get('url') == target
            and isinstance(data.get('events'), list) and 'MESSAGES_UPSERT' in data['events']
            and all(actual_headers.get(key.lower()) == value for key, value in required_headers.items())
            and not data.get('webhookByEvents', data.get('byEvents', False))
            and not data.get('webhookBase64', data.get('base64', False)))

    if matches(current):
        return False
    # Replace old tokens case-insensitively; preserve unrelated integrations' headers/events.
    token_names = {key.lower() for key in required_headers}
    headers = {key: value for key, value in headers.items() if key.lower() not in token_names}
    evolution.request('POST', '/webhook/set/' + name, {'webhook': {
        'enabled': True, 'url': target, 'headers': {**headers, **required_headers},
        'byEvents': False, 'base64': False,
        'events': list(dict.fromkeys(events + ['MESSAGES_UPSERT'])),
    }})
    if not matches(evolution.request('GET', '/webhook/find/' + name)):
        raise WebhookSetupError('O recebimento ainda não foi confirmado. Tente novamente em instantes.')
    return True
