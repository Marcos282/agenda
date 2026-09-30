import json
import re
from django.utils import timezone
from .models import Tenant
from .checkout_pro import approve_payment

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .mercado_pago import MercadoPagoError, process_webhook, verify_webhook_signature, valid_subscription_id, _masked_id


@csrf_exempt
@require_POST
def mercado_pago_webhook(request):
    response = _handle_webhook(request)
    tenant = getattr(request, "tenant", None)
    if tenant is not None:
        # Store only bounded, selected metadata; never headers or raw bodies.
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        event = request.GET.get("type") or payload.get("type") or request.GET.get("topic")
        data = payload.get('data')
        data = data if isinstance(data, dict) else {}
        identifier = str(request.GET.get('data.id') or data.get('id') or '')
        safe_identifier = _masked_id(identifier) if valid_subscription_id(identifier) else '[ausente ou inválido]'
        known = event in ("payment", "subscription_preapproval", "subscription_authorized_payment")
        Tenant.objects.filter(pk=tenant.pk).update(mercado_pago_ultimo_webhook={
            "received_at": timezone.now().isoformat(),
            "type": event if known else "outro ou ausente",
            "data": {"id": safe_identifier},
            "live_mode": payload.get("live_mode") if isinstance(payload.get("live_mode"), bool) else None,
            "http_status": response.status_code,
            "result": ("Processado" if known else "Evento ignorado") if response.status_code == 200 else "Rejeitado ou falha no processamento",
        })
    return response


def _handle_webhook(request):
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
    if event_type not in {'payment', 'subscription_preapproval', 'subscription_authorized_payment'}:
        return JsonResponse({'received': True})
    valid_id = valid_subscription_id(data_id) if event_type == 'subscription_preapproval' else re.fullmatch(r'[0-9]{1,100}', data_id)
    if not valid_id:
        return HttpResponse(status=400)
    if not verify_webhook_signature(
        signature=request.headers.get('x-signature', ''),
        request_id=request.headers.get('x-request-id', ''),
        data_id=data_id,
        secret=secret,
    ):
        return HttpResponse(status=401)
    try:
        if event_type == 'payment':
            tenant = getattr(request, 'tenant', None)
            approve_payment(data_id, tenant_id=tenant.pk if tenant else None)
        else:
            process_webhook(event_type=event_type, data_id=data_id)
    except MercadoPagoError:
        return HttpResponse(status=503)
    return JsonResponse({'received': True})
