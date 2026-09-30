import json

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from mercadopago.webhook import WebhookSignatureValidator, InvalidWebhookSignatureError

from .services import CheckoutError, confirmar_pagamento, valid_payment_id
from .models import NotificacaoMercadoPago


@csrf_exempt
@require_POST
def webhook(request):
    if not settings.MERCADO_PAGO_WEBHOOK_SECRET or not settings.MERCADO_PAGO_ACCESS_TOKEN:
        return HttpResponse(status=503)
    payment_id = request.GET.get('data.id', '')
    if not valid_payment_id(payment_id) or not request.headers.get('x-request-id'):
        return HttpResponse(status=400)
    try:
        WebhookSignatureValidator.validate(
            request.headers.get('x-signature'), request.headers.get('x-request-id'),
            payment_id, settings.MERCADO_PAGO_WEBHOOK_SECRET,
        )
    except InvalidWebhookSignatureError:
        return HttpResponse(status=401)
    if len(request.body) > 65536:
        return HttpResponse(status=413)
    try:
        raw_body = request.body.decode('utf-8')
        body = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(body, dict) or not isinstance(body.get('data'), dict):
        return HttpResponse(status=400)
    if str(body['data'].get('id')) != payment_id:
        return HttpResponse(status=400)
    notification = NotificacaoMercadoPago.objects.create(
        payment_id=payment_id,
        tipo=str(body.get('type', ''))[:80],
        evento=str(body.get('action', ''))[:100],
        request_id=request.headers['x-request-id'][:200],
        dado_bruto=raw_body,
    )
    if body.get('type') != 'payment':
        notification.estado = NotificacaoMercadoPago.Estado.IGNORADA
        notification.save(update_fields=['estado'])
        return HttpResponse(status=200)
    try:
        payment = confirmar_pagamento(payment_id)
    except CheckoutError:
        # A non-2xx response asks Mercado Pago to retry. No acknowledgement is lost.
        notification.estado = NotificacaoMercadoPago.Estado.AGUARDANDO_REENVIO
        notification.save(update_fields=['estado'])
        return HttpResponse(status=503)
    if payment is None:
        notification.estado = NotificacaoMercadoPago.Estado.SEM_CORRESPONDENCIA
        notification.save(update_fields=['estado'])
    else:
        notification.pagamento = payment
        notification.estado = NotificacaoMercadoPago.Estado.PROCESSADA
        notification.save(update_fields=['pagamento', 'estado'])
    return HttpResponse(status=200)
