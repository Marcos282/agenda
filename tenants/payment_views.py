import json
import re

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .mercado_pago import MercadoPagoError, process_webhook, verify_webhook_signature


@csrf_exempt
@require_POST
def mercado_pago_webhook(request):
    secret = settings.MERCADO_PAGO_WEBHOOK_SECRET.strip()
    if not secret:
        return HttpResponse(status=503)
    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(payload, dict):
        return HttpResponse(status=400)

    data = payload.get('data') or {}
    if not isinstance(data, dict):
        return HttpResponse(status=400)
    data_id = str(request.GET.get('data.id') or data.get('id') or '')
    event_type = str(request.GET.get('type') or payload.get('type') or request.GET.get('topic') or '')
    if event_type not in {'subscription_preapproval', 'subscription_authorized_payment'}:
        return JsonResponse({'received': True})
    if not re.fullmatch(r'[0-9]{1,100}', data_id):
        return HttpResponse(status=400)
    if not verify_webhook_signature(
        signature=request.headers.get('x-signature', ''),
        request_id=request.headers.get('x-request-id', ''),
        data_id=data_id,
        secret=secret,
    ):
        return HttpResponse(status=401)
    try:
        process_webhook(event_type=event_type, data_id=data_id)
    except MercadoPagoError:
        return HttpResponse(status=503)
    return JsonResponse({'received': True})
