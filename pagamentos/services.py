"""One-off Checkout Pro purchases of 30 days of platform access."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import logging
import re
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import mercadopago
import requests
from mercadopago.config import RequestOptions
from mercadopago.errors.exceptions import MercadoPagoError
from requests.exceptions import RequestException
from django.conf import settings
from django.core.exceptions import ValidationError
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
                and public_url())


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
    if diagnostico is not None and isinstance(result, dict):
        diagnostico['status_http'] = result.get('status')
        response = result.get('response')
        if isinstance(response, dict):
            diagnostico['resposta_api'] = {
                key: response[key] for key in (
                    'id', 'status', 'status_detail', 'error', 'message',
                    'external_reference', 'transaction_amount', 'currency_id',
                    'collector_id', 'live_mode', 'date_approved',
                ) if key in response and isinstance(response[key], (str, int, float, bool, type(None)))
            }
            for key, value in diagnostico['resposta_api'].items():
                if isinstance(value, str):
                    for secret in (settings.MERCADO_PAGO_ACCESS_TOKEN, settings.MERCADO_PAGO_WEBHOOK_SECRET):
                        if secret:
                            value = value.replace(secret, '[omitido]')
                    diagnostico['resposta_api'][key] = value[:500]
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


def criar_checkout(*, tenant_id, retorno_url, diagnostico=None, preparar=False, checkout_id=None, plano=None):
    if not configurado():
        raise CheckoutError('O pagamento online ainda não está configurado.')
    # Serialize repeated clicks for this tenant. A timeout never grants access.
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id, ativo=True)
        if plano is not None:
            tenant.plano = plano
        try:
            tenant.full_clean()
        except ValidationError as exc:
            raise CheckoutError(' '.join(exc.messages)) from exc
        amount = tenant.valor_plano
        checkouts = CheckoutAcesso.objects.filter(
            tenant_id=tenant_id, plano=tenant.plano, valor=amount, producao=settings.MERCADO_PAGO_LIVE_MODE,
            retorno_url=retorno_url, expira_em__gt=timezone.now(),
        ).exclude(pagamentos__creditado_em__isnull=False)
        checkout = checkouts.filter(pk=checkout_id).first() if checkout_id else checkouts.first()
        if checkout_id and checkout is None:
            raise CheckoutError('A prévia expirou ou foi alterada. Confira uma nova prévia antes de enviar.')
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
        if checkout is None:
            checkout = CheckoutAcesso.objects.create(
                tenant_id=tenant_id, plano=tenant.plano, valor=amount, retorno_url=retorno_url,
                producao=settings.MERCADO_PAGO_LIVE_MODE, expira_em=timezone.now() + timedelta(hours=24),
            )
        return_url = f'{retorno_url}?checkout={checkout.pk}'
        payload = {
            'items': [{'id': 'acesso-30-dias', 'title': f'Tá Combinado — {tenant.get_plano_display()} por 30 dias',
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
                'resultado': 'aguardando_envio' if preparar else 'preferencia_criada',
                'requisicao': {
                    'metodo': 'POST',
                    'endpoint': 'https://api.mercadopago.com/checkout/preferences',
                    'cabecalhos': {'x-idempotency-key': str(checkout.pk)},
                    'corpo': payload,
                },
            })
        if preparar:
            return checkout
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


def consultar_recebedor():
    """Fetch seller identity without exposing the authorization header."""
    response = requests.get(
        'https://api.mercadopago.com/users/me',
        headers={'Authorization': f'Bearer {settings.MERCADO_PAGO_ACCESS_TOKEN}'},
        timeout=5,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return {'status': response.status_code, 'response': payload}


def ambiente_compativel(payment, checkout, diagnostico=None):
    live_mode = payment.get('live_mode')
    if type(live_mode) is not bool:
        return False
    if live_mode is checkout.producao:
        return True
    # Checkout Pro test sellers may return live_mode=true. Only allow this
    # exception for a test checkout after verifying the authenticated seller.
    if checkout.producao or not live_mode:
        return False
    seller = api_call(consultar_recebedor)
    tags = seller.get('tags')
    is_test = isinstance(tags, list) and 'test_user' in tags
    same_seller = str(seller.get('id')) == checkout.recebedor_id
    if diagnostico is not None:
        diagnostico['verificacao_recebedor'] = {
            'id': str(seller.get('id', ''))[:100],
            'conta_de_teste': is_test,
            'corresponde_a_cobranca': same_seller,
        }
    return same_seller and is_test


def confirmar_pagamento(payment_id, *, tenant_id=None, checkout_id=None, diagnostico=None):
    """Reconcile using authenticated provider data, never the browser's status."""
    if not valid_payment_id(payment_id):
        return None
    client = sdk()
    payment = api_call(client.payment().get, payment_id, diagnostico=diagnostico)
    try:
        reference = UUID(str(payment.get('external_reference', '')))
        amount = Decimal(str(payment.get('transaction_amount', '')))
    except (ValueError, TypeError, InvalidOperation):
        return None
    checkout = CheckoutAcesso.objects.filter(pk=reference).first()
    def recusar(motivo):
        if diagnostico is not None:
            diagnostico['motivo_nao_validado'] = motivo
        return None

    if not checkout:
        return recusar('Checkout não encontrado neste banco de dados.')
    if ((tenant_id is not None and checkout.tenant_id != tenant_id)
            or (checkout_id is not None and str(checkout.pk) != str(checkout_id))):
        return recusar('Pagamento não pertence ao estabelecimento ou checkout solicitado.')
    if (str(payment.get('id')) != payment_id or not amount.is_finite()
            or amount != checkout.valor or payment.get('currency_id') != 'BRL'
            or str(payment.get('collector_id')) != checkout.recebedor_id):
        return recusar('ID, valor, moeda ou recebedor diverge da cobrança.')
    if diagnostico is not None:
        diagnostico['ambiente_checkout'] = 'producao' if checkout.producao else 'teste'
    if not ambiente_compativel(payment, checkout, diagnostico):
        return recusar('Ambiente incompatível: conta vendedora não confirmada como teste para esta cobrança.')
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
            return recusar('A ordem do Mercado Pago não corresponde à preferência da cobrança.')
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
            tenant.plano = checkout.plano
            try:
                tenant.full_clean()
            except ValidationError as exc:
                raise CheckoutError('Pagamento recebido, mas a troca de plano aguarda a desativação dos profissionais extras. ' + ' '.join(exc.messages)) from exc
            today = timezone.localdate(timezone=ZoneInfo(tenant.timezone))
            tenant.expira_em = max(today, tenant.data_expiracao) + timedelta(days=checkout.dias)
            tenant.save(update_fields=['expira_em', 'plano', 'atualizado_em'])
            record.creditado_em = timezone.now()
        record.save(update_fields=['status', 'creditado_em', 'atualizado_em'])
        return record
