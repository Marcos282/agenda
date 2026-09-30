import hashlib
import hmac
import json
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import PlataformaPagamento, Tenant

logger = logging.getLogger(__name__)
API_BASE = 'https://api.mercadopago.com'


class MercadoPagoError(Exception):
    def __init__(self, message, *, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def _mask_email(value):
    if not isinstance(value, str) or '@' not in value:
        return '[ausente]'
    local, domain = value.rsplit('@', 1)
    return f'{local[:1]}***@{domain}'


def _safe_url(value):
    parsed = urlparse(value if isinstance(value, str) else '')
    if not parsed.scheme or not parsed.hostname:
        return '[inválida]'
    return f'{parsed.scheme}://{parsed.hostname}{parsed.path}'


def _masked_id(value):
    value = str(value or '')
    return f'…{value[-4:]}' if value else '[ausente]'


def _safe_text(value, limit=300):
    text = str(value or '')[:limit]
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[e-mail redigido]', text)
    text = re.sub(r'\b(?:APP_USR|TEST)-[A-Za-z0-9_-]{10,}\b', '[credencial redigida]', text)
    return text


def _request_summary(method, path, payload, idempotency_key):
    summary = {
        'method': method,
        'path': path,
        'authorization': '[redigido]',
        'idempotency_key': '[configurada]' if idempotency_key else '[ausente]',
    }
    if payload is not None:
        recurring = payload.get('auto_recurring')
        summary['payload'] = {
            'reason': payload.get('reason'),
            'external_reference': '[redigida]' if payload.get('external_reference') else '[ausente]',
            'payer_email': _mask_email(payload.get('payer_email')),
            'back_url': _safe_url(payload.get('back_url')),
            'notification_url': _safe_url(payload.get('notification_url')),
            'auto_recurring': {
                key: recurring.get(key)
                for key in ('frequency', 'frequency_type', 'transaction_amount', 'currency_id')
                if isinstance(recurring, dict) and key in recurring
            },
        }
    return summary


def _response_summary(result, *, status_code, error=None):
    summary = {'http_status': status_code}
    if error:
        summary.update({
            'error': str(error.get('error', ''))[:100],
            'message': _safe_text(error.get('message', '')),
            'cause_codes': [
                str(cause.get('code', ''))[:100]
                for cause in error.get('cause', [])
                if isinstance(cause, dict) and cause.get('code')
            ][:10] if isinstance(error.get('cause', []), list) else [],
        })
        return summary
    summary['body'] = {
        'id': _masked_id(result.get('id')),
        'status': str(result.get('status', ''))[:50],
        'init_point': _safe_url(result.get('init_point')) if result.get('init_point') else '[ausente]',
    }
    return summary


def valid_subscription_id(value):
    # Preapproval IDs are opaque alphanumeric strings, unlike numeric payment IDs.
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9]{1,100}', value))


def configured():
    return bool(settings.MERCADO_PAGO_ACCESS_TOKEN.strip() and settings.MERCADO_PAGO_WEBHOOK_SECRET.strip())


def _request(method, path, *, payload=None, idempotency_key=None, diagnostics=None):
    request_info = _request_summary(method, path, payload, idempotency_key)
    token = settings.MERCADO_PAGO_ACCESS_TOKEN.strip()
    if not token:
        if diagnostics is not None:
            diagnostics.update({'request': request_info, 'response': {'error': 'Credencial não configurada'}})
        raise MercadoPagoError(
            'A integração com Mercado Pago não está configurada.',
            diagnostics={'request': request_info},
        )
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload).encode()
    if idempotency_key:
        headers['X-Idempotency-Key'] = str(idempotency_key)
    request = Request(API_BASE + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
            status_code = response.status
    except HTTPError as exc:
        try:
            error_response = json.loads(exc.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            error_response = {}
        error_name = error_response.get('error', '') if isinstance(error_response, dict) else ''
        message = error_response.get('message', '') if isinstance(error_response, dict) else ''
        causes = error_response.get('cause', []) if isinstance(error_response, dict) else []
        cause_codes = [
            str(cause.get('code', ''))
            for cause in causes
            if isinstance(cause, dict) and cause.get('code')
        ] if isinstance(causes, list) else []
        logger.warning(
            'Mercado Pago API rejected %s: HTTP %s, error=%s, message=%s, cause_codes=%s',
            path, exc.code, _safe_text(error_name), _safe_text(message), [_safe_text(code) for code in cause_codes],
        )
        response_info = _response_summary(
            error_response if isinstance(error_response, dict) else {},
            status_code=exc.code,
            error=error_response if isinstance(error_response, dict) else {},
        )
        if diagnostics is not None:
            diagnostics.update({'request': request_info, 'response': response_info})
        safe_message = _safe_text(message)
        if exc.code == 400 and 'both payer and collector must be real or test users' in str(message).lower():
            raise MercadoPagoError(
                'O Mercado Pago recusou a solicitação (HTTP 400): comprador e vendedor estão em ambientes diferentes. '
                'Para testar, use uma conta compradora de teste com a conta vendedora de teste. '
                'Para cobrar de verdade, as duas contas precisam ser reais.',
                diagnostics={'request': request_info, 'response': response_info},
            ) from exc
        if exc.code < 500 and safe_message:
            detail = f' O Mercado Pago informou: {safe_message}'
            if cause_codes:
                detail += f' (código {", ".join(cause_codes)}).'
            raise MercadoPagoError(
                f'O Mercado Pago recusou a solicitação (HTTP {exc.code}).{detail}',
                diagnostics={'request': request_info, 'response': response_info},
            ) from exc
        raise MercadoPagoError(
            f'Não foi possível confirmar a operação no Mercado Pago (HTTP {exc.code}). Tente novamente.',
            diagnostics={'request': request_info, 'response': response_info},
        ) from exc
    except (URLError, TimeoutError) as exc:
        logger.warning('Mercado Pago API is unavailable for %s', path)
        response_info = {'error': 'Falha de rede ou timeout'}
        if diagnostics is not None:
            diagnostics.update({'request': request_info, 'response': response_info})
        raise MercadoPagoError(
            'O Mercado Pago não respondeu. Tente novamente em alguns instantes.',
            diagnostics={'request': request_info, 'response': response_info},
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        response_info = {'error': 'Resposta JSON inválida'}
        if diagnostics is not None:
            diagnostics.update({'request': request_info, 'response': response_info})
        raise MercadoPagoError(
            'O Mercado Pago retornou uma resposta inválida.',
            diagnostics={'request': request_info, 'response': response_info},
        ) from exc
    if not isinstance(result, dict):
        response_info = {'error': 'Formato de resposta inválido'}
        if diagnostics is not None:
            diagnostics.update({'request': request_info, 'response': response_info})
        raise MercadoPagoError(
            'O Mercado Pago retornou uma resposta inválida.',
            diagnostics={'request': request_info, 'response': response_info},
        )
    if diagnostics is not None:
        diagnostics.update({
            'request': request_info,
            'response': _response_summary(result, status_code=status_code),
        })
    return result


def _public_url(tenant, path):
    base_domain = settings.STORE_BASE_DOMAIN.strip().lower()
    return f'https://{tenant.subdomain}.{base_domain}{path}'


def create_subscription(*, tenant_id, payer_email, amount, diagnostics=None):
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        if tenant.mercado_pago_assinatura_status in {'pending', 'authorized'}:
            if tenant.mercado_pago_assinatura_status == 'pending' and tenant.mercado_pago_checkout_url:
                return tenant.mercado_pago_checkout_url
            raise MercadoPagoError('Já existe uma assinatura ativa para este estabelecimento.')
        if tenant.mercado_pago_assinatura_id:
            tenant.mercado_pago_idempotency_key = uuid4()
            tenant.mercado_pago_assinatura_id = ''
            tenant.mercado_pago_assinatura_status = ''
            tenant.mercado_pago_checkout_url = ''
            tenant.save(update_fields=[
                'mercado_pago_idempotency_key', 'mercado_pago_assinatura_id',
                'mercado_pago_assinatura_status', 'mercado_pago_checkout_url',
            ])
        elif tenant.mercado_pago_idempotency_key is None:
            tenant.mercado_pago_idempotency_key = uuid4()
        tenant.mercado_pago_valor_assinatura = amount
        tenant.save(update_fields=['mercado_pago_idempotency_key', 'mercado_pago_valor_assinatura'])
        idempotency_key = tenant.mercado_pago_idempotency_key

    path = '/painel/mensalidade/'
    webhook_path = '/integracoes/mercado-pago/webhook/'
    external_reference = f'tacombinado-tenant-{tenant_id}:{idempotency_key}'
    result = _request('POST', '/preapproval', idempotency_key=idempotency_key, payload={
        'reason': 'Assinatura mensal Tá Combinado',
        'external_reference': external_reference,
        'payer_email': payer_email,
        'back_url': _public_url(tenant, path),
        'notification_url': _public_url(tenant, webhook_path),
        'auto_recurring': {
            'frequency': 30,
            'frequency_type': 'days',
            'transaction_amount': float(amount),
            'currency_id': 'BRL',
        },
    }, diagnostics=diagnostics)
    checkout_url = result.get('init_point')
    if not isinstance(checkout_url, str):
        raise MercadoPagoError('O Mercado Pago não retornou um link de assinatura válido.')
    parsed = urlparse(checkout_url or '')
    if parsed.scheme != 'https' or not (
        parsed.hostname == 'mercadopago.com.br'
        or parsed.hostname == 'mercadopago.com'
        or (parsed.hostname or '').endswith('.mercadopago.com.br')
        or (parsed.hostname or '').endswith('.mercadopago.com')
    ):
        raise MercadoPagoError('O Mercado Pago não retornou um link de assinatura válido.')
    subscription_id = result.get('id')
    if not valid_subscription_id(subscription_id):
        raise MercadoPagoError('O Mercado Pago não retornou o identificador da assinatura.')
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        if tenant.mercado_pago_assinatura_id not in {'', subscription_id}:
            raise MercadoPagoError('Uma assinatura foi criada em outra solicitação. Atualize a página.')
        tenant.mercado_pago_assinatura_id = subscription_id
        if not tenant.mercado_pago_assinatura_status:
            tenant.mercado_pago_assinatura_status = str(result.get('status', 'pending'))
        tenant.mercado_pago_checkout_url = checkout_url
        tenant.save(update_fields=[
            'mercado_pago_assinatura_id', 'mercado_pago_assinatura_status',
            'mercado_pago_checkout_url',
        ])
    return checkout_url


def verify_webhook_signature(*, signature, request_id, data_id, secret):
    if not signature or not request_id or not data_id or not secret:
        return False
    values = {}
    for part in signature.split(','):
        key, separator, value = part.strip().partition('=')
        if separator:
            values[key] = value
    timestamp, received = values.get('ts'), values.get('v1')
    if not timestamp or not received:
        return False
    manifest = f'id:{data_id.lower()};request-id:{request_id};ts:{timestamp};'
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def _tenant_from_external_reference(value):
    prefix = 'tacombinado-tenant-'
    if not isinstance(value, str) or not value.startswith(prefix):
        return None
    tenant_id, separator, key = value.removeprefix(prefix).partition(':')
    if not separator or not tenant_id.isdecimal():
        return None
    tenant = Tenant.objects.filter(pk=int(tenant_id), ativo=True).first()
    if tenant is None or str(tenant.mercado_pago_idempotency_key) != key:
        return None
    return tenant


def _matches_external_reference(tenant, value):
    return value == f'tacombinado-tenant-{tenant.pk}:{tenant.mercado_pago_idempotency_key}'


def _save_subscription_status(subscription):
    subscription_id = subscription.get('id')
    external_reference = subscription.get('external_reference')
    tenant = _tenant_from_external_reference(external_reference)
    if not tenant or not valid_subscription_id(subscription_id):
        return
    with transaction.atomic():
        locked = Tenant.objects.select_for_update().get(pk=tenant.pk)
        if (_matches_external_reference(locked, external_reference)
                and locked.mercado_pago_assinatura_id in {'', subscription_id}):
            locked.mercado_pago_assinatura_id = subscription_id
            locked.mercado_pago_assinatura_status = str(subscription.get('status', ''))
            if subscription.get('init_point'):
                locked.mercado_pago_checkout_url = subscription['init_point']
            locked.save(update_fields=[
                'mercado_pago_assinatura_id', 'mercado_pago_assinatura_status',
                'mercado_pago_checkout_url',
            ])


def _approve_authorized_payment(authorized_payment_id):
    if not re.fullmatch(r'[0-9]{1,100}', authorized_payment_id):
        return
    authorized = _request('GET', f'/authorized_payments/{authorized_payment_id}')
    subscription_id = authorized.get('preapproval_id')
    payment_id = str((authorized.get('payment') or {}).get('id', ''))
    if not valid_subscription_id(subscription_id) or not re.fullmatch(r'[0-9]{1,100}', payment_id):
        return
    subscription = _request('GET', f'/preapproval/{subscription_id}')
    external_reference = subscription.get('external_reference')
    tenant = _tenant_from_external_reference(external_reference)
    if not tenant:
        return
    payment = _request('GET', f'/v1/payments/{payment_id}')
    if payment.get('status') != 'approved' or payment.get('currency_id') != 'BRL':
        return
    try:
        amount = Decimal(str(payment.get('transaction_amount', '0')))
    except InvalidOperation:
        logger.error('Mercado Pago payment amount is invalid; payment was not applied')
        return
    expected_amount = tenant.mercado_pago_valor_assinatura
    if expected_amount is None:
        logger.error('Tenant %s has no recorded Mercado Pago subscription amount', tenant.pk)
        return
    if amount != expected_amount:
        logger.warning('Mercado Pago payment amount mismatch for tenant %s', tenant.pk)
        return
    approved_at = parse_datetime(payment.get('date_approved', '')) if payment.get('date_approved') else None
    tenant_zone = ZoneInfo(tenant.timezone)
    if approved_at is None:
        payment_date = timezone.localdate(timezone=tenant_zone)
    else:
        if timezone.is_naive(approved_at):
            approved_at = timezone.make_aware(approved_at, tenant_zone)
        payment_date = timezone.localtime(approved_at, tenant_zone).date()
    with transaction.atomic():
        locked = Tenant.objects.select_for_update().get(pk=tenant.pk)
        if (not _matches_external_reference(locked, external_reference)
                or locked.mercado_pago_assinatura_id not in {'', subscription_id}):
            return
        if PlataformaPagamento.objects.filter(mercado_pago_payment_id=payment_id).exists():
            return
        if locked.mercado_pago_assinatura_id == '':
            locked.mercado_pago_assinatura_id = subscription_id
            locked.mercado_pago_assinatura_status = str(subscription.get('status', ''))
        try:
            with transaction.atomic():
                PlataformaPagamento.objects.create(
                    tenant=locked,
                    mercado_pago_payment_id=payment_id,
                    mercado_pago_assinatura_id=subscription_id,
                    valor=amount,
                    aprovado_em=approved_at,
                )
        except IntegrityError:
            return
        base_date = max(locked.data_expiracao, payment_date)
        locked.expira_em = base_date + timedelta(days=30)
        locked.save(update_fields=[
            'expira_em', 'mercado_pago_assinatura_id', 'mercado_pago_assinatura_status',
        ])


def process_webhook(*, event_type, data_id):
    if event_type == 'subscription_preapproval':
        _save_subscription_status(_request('GET', f'/preapproval/{data_id}'))
    elif event_type == 'subscription_authorized_payment':
        _approve_authorized_payment(data_id)
