"""Authenticated Evolution callback for the test inbox."""
import json
from secrets import compare_digest
from django.http import JsonResponse
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from tenants.decorators import tenant_required
from usuarios.validators import normalizar_whatsapp
from . import evolution, inbox


def webhook_token(tenant):
    return salted_hmac('whatsapp.tests.inbox', str(tenant.pk), algorithm='sha256').hexdigest()


def webhook_url(request):
    route = 'whatsapp_test_receive_single' if request.resolver_match.url_name == 'teste' else 'whatsapp_test_receive'
    return request.build_absolute_uri(reverse(route)) + '?token=' + webhook_token(request.tenant)


@csrf_exempt
@tenant_required
@require_POST
def receive(request):
    token = request.headers.get('X-TestZap-Token', '') or request.GET.get('token', '')
    if not compare_digest(token.encode(), webhook_token(request.tenant).encode()):
        return JsonResponse({'error': 'Autenticação inválida.'}, status=403)
    if int(request.META.get('CONTENT_LENGTH') or 0) > 65536:
        return JsonResponse({'error': 'Mensagem muito grande.'}, status=413)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError
        if payload.get('instance') != evolution.instance(request.tenant):
            return JsonResponse({'error': 'Instância incorreta.'}, status=403)
        if payload.get('event', '').lower().replace('_', '.') != 'messages.upsert':
            return JsonResponse({'ignored': True})
        data = payload.get('data')
        items = data if isinstance(data, list) else [data]
        stored = 0
        for item in items:
            if not isinstance(item, dict):
                raise ValueError
            key = item.get('key') or {}
            message = item.get('message') or {}
            if not isinstance(key, dict) or not isinstance(message, dict):
                raise ValueError
            if key.get('fromMe') is not False:
                continue
            jid = key.get('remoteJid', '')
            if jid.endswith('@lid'):
                jid = key.get('remoteJidAlt', '')
            if not jid.endswith('@s.whatsapp.net'):
                continue
            number = normalizar_whatsapp('+' + jid.split('@')[0])
            extended = message.get('extendedTextMessage') or {}
            text = message.get('conversation') or (extended.get('text') if isinstance(extended, dict) else '')
            message_id = key.get('id')
            if not isinstance(text, str) or not text:
                continue
            if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
                raise ValueError
            stored += inbox.save_message(request.tenant.pk, message_id, number, text)
        return JsonResponse({'received': stored})
    except (ValueError, TypeError, AttributeError, ValidationError):
        return JsonResponse({'error': 'Mensagem inválida.'}, status=400)
