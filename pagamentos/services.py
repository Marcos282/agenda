"""One-off Checkout Pro purchases of 30 days of platform access."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import logging
import re
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import mercadopago
from mercadopago.config import RequestOptions
from mercadopago.errors.exceptions import MercadoPagoError
from requests.exceptions import RequestException
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tenants.models import Tenant
from .models import CheckoutAcesso, PagamentoAcesso

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    pass


def provider_error(status):
    if status in (401, 403):
        return CheckoutError(
            'O Mercado Pago não autorizou a operação. O administrador da plataforma '
            'precisa conferir o Access Token e as permissões da aplicação.'
        )
    return CheckoutError('Não foi possível confirmar a operação no Mercado Pago. Tente novamente.')


def preco_acesso():
    try:
        value = Decimal(str(settings.PLATFORM_ACCESS_PRICE))
        if value.is_finite() and 0 < value <= Decimal('999999.99') and value == value.quantize(Decimal('.01')):
            return value
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def public_url():
    value = settings.MERCADO_PAGO_PUBLIC_URL
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'https' and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ('', '/') and parsed.port in (None, 443)):
            return value.rstrip('/')
    except ValueError:
        pass
    return ''


def configurado():
    return bool(settings.MERCADO_PAGO_ACCESS_TOKEN and settings.MERCADO_PAGO_WEBHOOK_SECRET
                and public_url() and preco_acesso() is not None)


def sdk():
    if not settings.MERCADO_PAGO_ACCESS_TOKEN:
        raise CheckoutError('O pagamento online ainda não está configurado.')
    return mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN,
                          request_options=RequestOptions(connection_timeout=5.0, max_retries=0))


def api_call(method, *args, diagnostico=None):
    try:
        result = method(*args)
    except (MercadoPagoError, RequestException) as exc:
        # Do not persist provider payloads: they may contain credentials or payer data.
        logger.warning('Checkout Pro API unavailable (HTTP %s)', getattr(exc, 'status_code', 0))
        raise provider_error(getattr(exc, 'status_code', 0)) from None
    if isinstance(result, dict) and result.get('status') in (401, 403):
        logger.warning('Checkout Pro API unauthorized (HTTP %s)', result['status'])
        raise provider_error(result['status'])
    if (not isinstance(result, dict) or result.get('status') not in (200, 201)
            or not isinstance(result.get('response'), dict)):
        raise CheckoutError('O Mercado Pago não retornou uma resposta válida. Tente novamente.')
    if diagnostico is not None:
        diagnostico['status_http'] = result['status']
    return result['response']


def valid_payment_id(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{1,100}', value) is not None


def valid_checkout_url(value):
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and any(
                    parsed.hostname == domain or (parsed.hostname or '').endswith('.' + domain)
                    for domain in ('mercadopago.com', 'mercadopago.com.br')))
    except ValueError:
        return False


def criar_checkout(*, tenant_id, retorno_url, diagnostico=None):
    if not configurado():
        raise CheckoutError('O pagamento online ainda não está configurado.')
    amount = preco_acesso()
    # Serialize repeated clicks for this tenant. A timeout never grants access.
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=tenant_id, ativo=True)
        checkout = CheckoutAcesso.objects.filter(
            tenant_id=tenant_id, valor=amount, producao=settings.MERCADO_PAGO_LIVE_MODE,
            retorno_url=retorno_url, expira_em__gt=timezone.now(),
        ).exclude(pagamentos__creditado_em__isnull=False).first()
        if checkout and valid_checkout_url(checkout.checkout_url):
            if diagnostico is not None:
                diagnostico.update({
                    'resultado': 'checkout_existente_reutilizado',
                    'requisicao': None,
                    'resposta': {
                        'id': checkout.preferencia_id,
                        'checkout_host': urlsplit(checkout.checkout_url).hostname,
                    },
                })
            return checkout
        checkout = CheckoutAcesso.objects.create(
            tenant_id=tenant_id, valor=amount, retorno_url=retorno_url,
            producao=settings.MERCADO_PAGO_LIVE_MODE, expira_em=timezone.now() + timedelta(hours=24),
        )
        return_url = f'{retorno_url}?checkout={checkout.pk}'
        payload = {
            'items': [{'id': 'acesso-30-dias', 'title': 'Tá Combinado — acesso por 30 dias',
                       'description': 'Pagamento avulso, sem renovação automática.',
                       'quantity': 1, 'currency_id': 'BRL', 'unit_price': float(amount)}],
            'external_reference': str(checkout.pk),
            'back_urls': {state: return_url for state in ('success', 'pending', 'failure')},
            'auto_return': 'approved',
            'expires': True,
            'expiration_date_to': checkout.expira_em.isoformat(timespec='seconds'),
        }
        options = RequestOptions(connection_timeout=5.0, max_retries=0,
                                 custom_headers={'x-idempotency-key': str(checkout.pk)})
        if diagnostico is not None:
            diagnostico.update({
                'resultado': 'preferencia_criada',
                'requisicao': {
                    'metodo': 'POST',
                    'endpoint': 'https://api.mercadopago.com/checkout/preferences',
                    'cabecalhos': {'x-idempotency-key': str(checkout.pk)},
                    'corpo': payload,
                },
            })
        result = api_call(sdk().preference().create, payload, options, diagnostico=diagnostico)
        if diagnostico is not None:
            init_point = result.get('init_point')
            sandbox_init_point = result.get('sandbox_init_point')
            diagnostico['resposta'] = {
                'status_http': diagnostico.get('status_http'),
                'id': str(result.get('id', ''))[:200],
                'collector_id': str(result.get('collector_id', ''))[:100],
                'init_point_host': urlsplit(init_point).hostname if isinstance(init_point, str) else None,
                'sandbox_init_point_host': (
                    urlsplit(sandbox_init_point).hostname if isinstance(sandbox_init_point, str) else None
                ),
            }
        url = result.get('init_point')
        preference_id = result.get('id')
        collector = str(result.get('collector_id', ''))
        if (not valid_checkout_url(url) or not isinstance(preference_id, str)
                or not 1 <= len(preference_id) <= 200 or not valid_payment_id(collector)):
            raise CheckoutError('O Mercado Pago não retornou um checkout válido. Tente novamente.')
        checkout.preferencia_id = preference_id
        checkout.recebedor_id = collector
        checkout.checkout_url = url
        checkout.save(update_fields=['preferencia_id', 'recebedor_id', 'checkout_url'])
        return checkout


def confirmar_pagamento(payment_id, *, tenant_id=None, checkout_id=None):
    """Reconcile using authenticated provider data, never the browser's status."""
    if not valid_payment_id(payment_id):
        return None
    client = sdk()
    payment = api_call(client.payment().get, payment_id)
    try:
        reference = UUID(str(payment.get('external_reference', '')))
        amount = Decimal(str(payment.get('transaction_amount', '')))
    except (ValueError, TypeError, InvalidOperation):
        return None
    checkout = CheckoutAcesso.objects.filter(pk=reference).first()
    if (not checkout or (tenant_id is not None and checkout.tenant_id != tenant_id)
            or (checkout_id is not None and str(checkout.pk) != str(checkout_id))
            or str(payment.get('id')) != payment_id or not amount.is_finite()
            or amount != checkout.valor or payment.get('currency_id') != 'BRL'
            or str(payment.get('collector_id')) != checkout.recebedor_id
            or payment.get('live_mode') is not checkout.producao):
        return None
    status = payment.get('status')
    if status not in {'approved', 'pending', 'in_process', 'authorized', 'in_mediation',
                      'rejected', 'cancelled', 'refunded', 'charged_back'}:
        return None
    if status == 'approved':
        try:
            refunded = Decimal(str(payment.get('transaction_amount_refunded', 0)))
        except InvalidOperation:
            return None
        if not refunded.is_finite() or refunded != 0:
            return None
        order = payment.get('order') or {}
        if not isinstance(order, dict) or not valid_payment_id(str(order.get('id', ''))):
            return None
        merchant_order = api_call(client.merchant_order().get, str(order['id']))
        if merchant_order.get('preference_id') != checkout.preferencia_id:
            return None
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=checkout.tenant_id)
        record, _ = PagamentoAcesso.objects.get_or_create(
            payment_id=payment_id, defaults={'checkout': checkout, 'status': status},
        )
        if record.checkout_id != checkout.pk:
            return None
        # A delayed pending response must not hide a previously granted purchase.
        if record.creditado_em is None or status not in {'pending', 'in_process', 'authorized'}:
            record.status = status
        if status == 'approved' and record.creditado_em is None:
            today = timezone.localdate(timezone=ZoneInfo(tenant.timezone))
            tenant.expira_em = max(today, tenant.data_expiracao) + timedelta(days=checkout.dias)
            tenant.save(update_fields=['expira_em'])
            record.creditado_em = timezone.now()
        record.save(update_fields=['status', 'creditado_em', 'atualizado_em'])
        return record
