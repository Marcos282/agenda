import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .mercado_pago import MercadoPagoError, _request, _public_url
from .models import PlataformaCheckout, PlataformaPagamento, Tenant


def pending_checkout(tenant):
    return tenant.checkouts_plataforma.filter(
        aprovado=False, expira_em__gt=timezone.now(),
    ).exclude(checkout_url='').order_by('-criado_em').first()


def create_checkout(*, tenant_id, amount, diagnostics=None):
    # Serialize clicks for this establishment, including preference creation.
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        if tenant.mercado_pago_assinatura_status == 'authorized':
            raise MercadoPagoError('Existe uma assinatura automática ativa. Cancele-a no Mercado Pago antes de pagar avulso.')
        current = pending_checkout(tenant)
        if current and current.valor == amount:
            if diagnostics is not None:
                diagnostics.update(tenant.mercado_pago_diagnostico)
            return current.checkout_url
        attempt = PlataformaCheckout.objects.create(
            tenant=tenant, valor=amount, expira_em=timezone.now() + timedelta(hours=24),
        )
        back_url = _public_url(tenant, '/painel/mensalidade/')
        result = _request('POST', '/checkout/preferences', idempotency_key=attempt.referencia, payload={
            'items': [{'id': 'renovacao-30-dias', 'title': 'Tá Combinado — acesso por 30 dias',
                       'quantity': 1, 'unit_price': float(amount), 'currency_id': 'BRL'}],
            'external_reference': f'tacombinado-checkout-{attempt.referencia}',
            'back_urls': {status: back_url for status in ('success', 'failure', 'pending')},
            'auto_return': 'approved',
            'notification_url': _public_url(tenant, '/integracoes/mercado-pago/webhook/'),
            'expires': True,
            'expiration_date_to': attempt.expira_em.isoformat(),
        }, diagnostics=diagnostics)
        # Checkout Pro uses init_point, including when testing with test accounts.
        checkout_url = result.get('init_point')
        try:
            parsed = urlparse(checkout_url if isinstance(checkout_url, str) else '')
            valid_url = parsed.scheme == 'https' and any(
                parsed.hostname == domain or (parsed.hostname or '').endswith('.' + domain)
                for domain in ('mercadopago.com', 'mercadopago.com.br')
            ) and not parsed.username and not parsed.password
        except ValueError:
            valid_url = False
        preference_id = result.get('id')
        collector_id = str(result.get('collector_id', ''))
        if not valid_url or not isinstance(preference_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', preference_id):
            raise MercadoPagoError('O Mercado Pago não retornou um checkout válido.', diagnostics=diagnostics)
        if not re.fullmatch(r'[0-9]{1,100}', collector_id):
            raise MercadoPagoError('O Mercado Pago não identificou o recebedor do pagamento.', diagnostics=diagnostics)
        attempt.preference_id = preference_id
        attempt.collector_id = collector_id
        attempt.checkout_url = checkout_url
        attempt.save(update_fields=['preference_id', 'collector_id', 'checkout_url'])
        return checkout_url


def approve_payment(payment_id, *, tenant_id=None):
    if not re.fullmatch(r'[0-9]{1,100}', str(payment_id)):
        return
    payment = _request('GET', f'/v1/payments/{payment_id}')
    if str(payment.get('id')) != str(payment_id) or payment.get('status') != 'approved' or payment.get('currency_id') != 'BRL':
        return
    reference = payment.get('external_reference')
    prefix = 'tacombinado-checkout-'
    if not isinstance(reference, str) or not reference.startswith(prefix):
        return
    try:
        checkout_reference = UUID(reference[len(prefix):])
        amount = Decimal(str(payment.get('transaction_amount')))
        approved_at = parse_datetime(payment.get('date_approved') or '')
    except (ValueError, TypeError, InvalidOperation):
        return
    if not amount.is_finite() or approved_at is None or timezone.is_naive(approved_at):
        return
    attempt = PlataformaCheckout.objects.filter(referencia=checkout_reference).first()
    if attempt is None or (tenant_id is not None and attempt.tenant_id != tenant_id):
        return
    if amount != attempt.valor or str(payment.get('collector_id')) != attempt.collector_id:
        return
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=attempt.tenant_id)
        if PlataformaPagamento.objects.filter(mercado_pago_payment_id=str(payment_id)).exists():
            return
        try:
            with transaction.atomic():
                PlataformaPagamento.objects.create(
                    tenant=tenant, mercado_pago_payment_id=str(payment_id),
                    mercado_pago_assinatura_id='', valor=amount, aprovado_em=approved_at,
                )
        except IntegrityError:
            return
        payment_date = timezone.localtime(approved_at, ZoneInfo(tenant.timezone)).date()
        tenant.expira_em = max(tenant.data_expiracao, payment_date) + timedelta(days=30)
        tenant.save(update_fields=['expira_em'])
        PlataformaCheckout.objects.filter(pk=attempt.pk).update(aprovado=True)
