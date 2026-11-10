import json
from secrets import compare_digest

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from tenants.decorators import tenant_required
from . import evolution
from .replies import parse_messages, process_reply


def webhook_token(tenant):
    return salted_hmac('whatsapp.appointment.replies', str(tenant.pk), algorithm='sha256').hexdigest()


def process_payload(tenant, payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid payload')
    if payload.get('instance') != evolution.instance(tenant):
        return JsonResponse({'error': 'Instância incorreta.'}, status=403)
    parsed = parse_messages(payload)
    for item in parsed:
        process_reply(tenant, item)
    return JsonResponse({'received': len(parsed)})


@csrf_exempt
@tenant_required
@require_POST
def receive(request):
    if not compare_digest(request.headers.get('X-Agendamento-Token', '').encode(),
                          webhook_token(request.tenant).encode()):
        return JsonResponse({'error': 'Autenticação inválida.'}, status=403)
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > 65536 or len(request.body) > 65536:
            return JsonResponse({'error': 'Mensagem muito grande.'}, status=413)
        return process_payload(request.tenant, json.loads(request.body))
    except (ValueError, TypeError, AttributeError, ValidationError):
        return JsonResponse({'error': 'Mensagem inválida.'}, status=400)
