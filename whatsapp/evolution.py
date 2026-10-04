import base64
import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError, HTTPError
from django.conf import settings


class EvolutionError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def configured():
    return bool(settings.EVOLUTION_API_URL and settings.EVOLUTION_API_KEY)


def instance(tenant):
    prefix = settings.EVOLUTION_INSTANCE_PREFIX
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', prefix):
        raise EvolutionError('Prefixo da instância inválido no servidor.')
    return f'{prefix}_{tenant.pk}'


def request(method, path, payload=None):
    if not configured():
        raise EvolutionError('Configure a URL e a chave da Evolution API no servidor.')
    req = Request(settings.EVOLUTION_API_URL.rstrip('/') + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'apikey': settings.EVOLUTION_API_KEY, 'Content-Type': 'application/json'}, method=method)
    try:
        with build_opener(NoRedirect).open(req, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        raise EvolutionError('Não foi possível concluir a operação na Evolution API. Verifique a conexão e a configuração.') from None


def connection_info(tenant):
    data = request('GET', '/instance/fetchInstances')
    if not isinstance(data, list):
        raise EvolutionError('Resposta inesperada da Evolution API.')
    for item in data:
        if not isinstance(item, dict):
            continue
        item = item.get('instance', item)
        if not isinstance(item, dict):
            continue
        if item.get('instanceName', item.get('name')) == instance(tenant):
            status = item.get('state') or item.get('connectionStatus') or 'unknown'
            if isinstance(status, dict):
                status = status.get('state', 'unknown')
            raw = item.get('ownerJid') or item.get('number') or ''
            number = str(raw).split('@', 1)[0].split(':', 1)[0].lstrip('+')
            number = '+' + number if re.fullmatch(r'[1-9][0-9]{7,14}', number) else ''
            return {'state': status, 'number': number if status == 'open' else ''}
    return {'state': 'missing', 'number': ''}


def state(tenant):
    return connection_info(tenant)['state']


def connect(tenant):
    if state(tenant) == 'missing':
        data = request('POST', '/instance/create', {'instanceName': instance(tenant), 'integration': 'WHATSAPP-BAILEYS', 'qrcode': True})
    else:
        data = request('GET', '/instance/connect/' + instance(tenant))
    if not isinstance(data, dict):
        raise EvolutionError('Resposta inesperada da Evolution API.')
    qr = data.get('qrcode', {})
    raw = (qr.get('base64') if isinstance(qr, dict) else qr) or data.get('base64', '')
    if not isinstance(raw, str):
        return ''
    if raw.startswith('data:image/png;base64,'):
        raw = raw.split(',', 1)[1]
    try:
        decoded = base64.b64decode(raw, validate=True)
        if decoded.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'data:image/png;base64,' + raw
    except (ValueError, TypeError):
        pass
    return ''


def send_text(tenant, number, text):
    data = request('POST', '/message/sendText/' + instance(tenant), {'number': number.lstrip('+'), 'text': text})
    if not isinstance(data, dict) or not isinstance(data.get('key'), dict) or not data['key'].get('id'):
        raise EvolutionError('A API não confirmou o envio. Confira a conversa antes de tentar novamente.')
<<<<<<< HEAD
=======

    # Store only delivery metadata, never credentials or the complete API payload.
    return {'provider': 'evolution', 'message_id': str(data['key']['id'])}


def find_messages(tenant, number):
    """Read a single conversation; filter again even if the API ignores its filter."""
    jid = number.lstrip('+') + '@s.whatsapp.net'
    data = request('POST', '/chat/findMessages/' + instance(tenant), {
        'where': {'key': {'remoteJid': jid}}, 'page': 1, 'offset': 30,
    })
    records = data.get('messages', data) if isinstance(data, dict) else data
    if isinstance(records, dict):
        records = records.get('records', [])
    if not isinstance(records, list):
        raise EvolutionError('Resposta inesperada ao consultar mensagens.')
    result = []
    for item in records:
        if not isinstance(item, dict):
            continue
        key = item.get('key') or {}
        if not isinstance(key, dict) or key.get('remoteJid') != jid:
            continue
        message = item.get('message') or {}
        if not isinstance(message, dict):
            continue
        extended = message.get('extendedTextMessage') or {}
        text = message.get('conversation') or (extended.get('text') if isinstance(extended, dict) else '')
        if text:
            result.append({'text': str(text), 'sent': bool(key.get('fromMe'))})
    return result[:30]
>>>>>>> d4ce4f7 (Primeiro envio: guia pronta)
