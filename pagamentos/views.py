import json

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from mercadopago.webhook import WebhookSignatureValidator, InvalidWebhookSignatureError

from .services import CheckoutError, confirmar_pagamento, valid_payment_id


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
    try:
        body = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(body, dict) or not isinstance(body.get('data'), dict):
        return HttpResponse(status=400)
    if str(body['data'].get('id')) != payment_id:
        return HttpResponse(status=400)
    if body.get('type') != 'payment':
        return HttpResponse(status=200)
    try:
        confirmar_pagamento(payment_id)
    except CheckoutError:
        # A non-2xx response asks Mercado Pago to retry. No acknowledgement is lost.
        return HttpResponse(status=503)
    return HttpResponse(status=200)
