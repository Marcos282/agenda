import hashlib
import hmac
import json
from io import BytesIO
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse

from tenants.models import PlataformaPagamento, Tenant
from usuarios.models import User


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
        self.status = 201

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


@override_settings(
    MERCADO_PAGO_ACCESS_TOKEN='test-access-token',
    MERCADO_PAGO_WEBHOOK_SECRET='test-webhook-secret',
    PLATFORM_MONTHLY_PRICE='30.00',
    STORE_BASE_DOMAIN='tacombinado.net',
)
class MercadoPagoBillingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')

    def test_checkout_creates_a_tenant_specific_monthly_subscription(self):
        from tenants.mercado_pago import create_subscription

        response = FakeResponse({
            'id': '123',
            'status': 'pending',
            'init_point': 'https://www.mercadopago.com.br/subscriptions/checkout?preapproval_id=123',
        })
        diagnostics = {}
        with patch('tenants.mercado_pago.urlopen', return_value=response) as send:
            checkout = create_subscription(
                tenant_id=self.tenant.pk, payer_email='owner@example.test', amount=30,
                diagnostics=diagnostics,
            )
        self.assertEqual(checkout, response_url := 'https://www.mercadopago.com.br/subscriptions/checkout?preapproval_id=123')
        self.tenant.refresh_from_db()
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, 'https://api.mercadopago.com/preapproval')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-access-token')
        self.assertEqual(payload['external_reference'], f'tacombinado-tenant-{self.tenant.pk}:{self.tenant.mercado_pago_idempotency_key}')
        self.assertEqual(payload['payer_email'], 'owner@example.test')
        self.assertEqual(payload['auto_recurring'], {
            'frequency': 30, 'frequency_type': 'days',
            'transaction_amount': 30.0, 'currency_id': 'BRL',
        })
        self.assertEqual(diagnostics['request']['payload']['payer_email'], 'o***@example.test')
        self.assertEqual(
            diagnostics['request']['payload']['back_url'],
            'https://marcos.tacombinado.net/painel/mensalidade/',
        )
        self.assertEqual(
            diagnostics['request']['payload']['notification_url'],
            'https://marcos.tacombinado.net/integracoes/mercado-pago/webhook/',
        )
        self.assertEqual(diagnostics['response']['body']['id'], '…123')
        self.assertEqual(
            diagnostics['response']['body']['init_point'],
            'https://www.mercadopago.com.br/subscriptions/checkout',
        )
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.mercado_pago_assinatura_id, '123')
        self.assertEqual(self.tenant.mercado_pago_checkout_url, response_url)
        self.assertEqual(self.tenant.mercado_pago_assinatura_status, 'pending')

    def test_provider_validation_error_is_reported_without_exposing_credentials(self):
        from tenants.mercado_pago import MercadoPagoError, _request

        error = HTTPError(
            'https://api.mercadopago.com/preapproval',
            400,
            'Bad Request',
            {},
            BytesIO(json.dumps({
                'error': 'bad_request',
                'message': 'payer_email is invalid',
                'cause': [{'code': 'payer_email_invalid'}],
            }).encode()),
        )
        with patch('tenants.mercado_pago.urlopen', side_effect=error):
            with self.assertRaises(MercadoPagoError) as raised:
                _request('POST', '/preapproval', payload={})
        self.assertIn('HTTP 400', str(raised.exception))
        self.assertIn('payer_email is invalid', str(raised.exception))
        self.assertIn('payer_email_invalid', str(raised.exception))
        self.assertNotIn('test-access-token', str(raised.exception))

    def _signed_webhook(self, data_id, event_type):
        request_id = 'request-test-123'
        timestamp = '1790700000'
        manifest = f'id:{data_id};request-id:{request_id};ts:{timestamp};'
        signature = hmac.new(
            b'test-webhook-secret', manifest.encode(), hashlib.sha256,
        ).hexdigest()
        return self.client.post(
            reverse('mercado_pago_webhook') + f'?type={event_type}',
            data=json.dumps({'type': event_type, 'data': {'id': data_id}}),
            content_type='application/json',
            HTTP_HOST='marcos.localhost',
            HTTP_X_SIGNATURE=f'ts={timestamp},v1={signature}',
            HTTP_X_REQUEST_ID=request_id,
        )

    def test_approved_payment_extends_remaining_period_once(self):
        self.tenant.expira_em = date(2026, 10, 15)
        self.tenant.mercado_pago_assinatura_id = '123'
        self.tenant.mercado_pago_assinatura_status = 'authorized'
        self.tenant.mercado_pago_idempotency_key = uuid4()
        self.tenant.mercado_pago_valor_assinatura = Decimal('30.00')
        self.tenant.save()
        external_reference = f'tacombinado-tenant-{self.tenant.pk}:{self.tenant.mercado_pago_idempotency_key}'
        provider_responses = {
            '/authorized_payments/789': {
                'preapproval_id': '123', 'payment': {'id': '456'},
            },
            '/preapproval/123': {
                'id': '123', 'external_reference': external_reference, 'status': 'authorized',
            },
            '/v1/payments/456': {
                'id': '456', 'status': 'approved', 'currency_id': 'BRL',
                'transaction_amount': 30, 'date_approved': '2026-09-29T12:00:00.000-04:00',
            },
        }
        with patch('tenants.mercado_pago._request', side_effect=lambda method, path, **kwargs: provider_responses[path]):
            response = self._signed_webhook('789', 'subscription_authorized_payment')
        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 11, 14))
        self.assertEqual(PlataformaPagamento.objects.filter(tenant=self.tenant).count(), 1)

        with patch('tenants.mercado_pago._request', side_effect=lambda method, path, **kwargs: provider_responses[path]) as fetch_again:
            repeated = self._signed_webhook('789', 'subscription_authorized_payment')
        self.assertEqual(repeated.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 11, 14))
        self.assertEqual(PlataformaPagamento.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(fetch_again.call_count, 3)

    def test_invalid_signature_does_not_call_provider(self):
        with patch('tenants.mercado_pago._request') as fetch:
            response = self.client.post(
                reverse('mercado_pago_webhook') + '?type=subscription_authorized_payment',
                data=json.dumps({'data': {'id': '123'}}),
                content_type='application/json',
                HTTP_HOST='marcos.localhost',
                HTTP_X_SIGNATURE='ts=1,v1=invalid',
                HTTP_X_REQUEST_ID='request-id',
            )
        self.assertEqual(response.status_code, 401)
        fetch.assert_not_called()
        self.assertFalse(PlataformaPagamento.objects.exists())

    def test_expired_tenant_retains_only_billing_panel_and_cannot_book(self):
        self.tenant.expira_em = date(2026, 9, 28)
        self.tenant.save()
        admin = User.objects.create_user('billing@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(admin)
        response = self.client.get('/painel/agenda/', HTTP_HOST='marcos.localhost')
        self.assertRedirects(response, reverse('painel:mensalidade'), fetch_redirect_response=False)
        billing = self.client.get(reverse('painel:mensalidade'), HTTP_HOST='marcos.localhost')
        self.assertEqual(billing.status_code, 200)
        self.assertContains(billing, 'Mensalidade')
        self.assertNotContains(billing, '>Agenda</a>')
        self.assertNotContains(billing, 'Minha conta')
        self.assertNotContains(billing, 'Meus agendamentos')
        booking = self.client.get('/agendamentos/servico/1/', HTTP_HOST='marcos.localhost')
        self.assertEqual(booking.status_code, 503)
        self.assertContains(booking, 'Agendamentos temporariamente indisponíveis', status_code=503)
