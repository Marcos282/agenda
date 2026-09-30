import hashlib
import hmac
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .checkout_pro import create_checkout, approve_payment
from .mercado_pago import MercadoPagoError
from .models import Tenant, PlataformaCheckout, PlataformaPagamento
from .test_mercado_pago import FakeResponse
from usuarios.models import User


@override_settings(MERCADO_PAGO_ACCESS_TOKEN='APP_USR-example', MERCADO_PAGO_WEBHOOK_SECRET='secret',
                   PLATFORM_MONTHLY_PRICE='30.00', STORE_BASE_DOMAIN='tacombinado.net')
class CheckoutProTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Checkout', subdomain='checkout', expira_em=date(2026, 10, 15))
        self.admin = User.objects.create_user('checkout@example.test', tenant=self.tenant, tipo='ADMIN')
        self.url = 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=123-abc'

    def create(self):
        diagnostics = {}
        with patch('tenants.mercado_pago.urlopen', return_value=FakeResponse({
            'id': '123-abc', 'collector_id': 456, 'init_point': self.url,
        })) as send:
            url = create_checkout(tenant_id=self.tenant.pk, amount=Decimal('30.00'), diagnostics=diagnostics)
        return url, send, diagnostics

    def payment(self, **overrides):
        attempt = PlataformaCheckout.objects.get()
        return dict({
            'id': 789, 'collector_id': 456, 'status': 'approved', 'currency_id': 'BRL',
            'transaction_amount': 30, 'external_reference': f'tacombinado-checkout-{attempt.referencia}',
            'date_approved': '2026-09-30T10:00:00-03:00',
        }, **overrides)

    def test_checkout_omits_payer_and_reuses_pending_preference(self):
        url, send, diagnostics = self.create()
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.mercadopago.com/checkout/preferences')
        payload = json.loads(request.data)
        self.assertNotIn('payer', payload)
        self.assertNotIn('payer_email', payload)
        self.assertNotIn('auto_recurring', payload)
        self.assertEqual(payload['items'][0]['unit_price'], 30)
        self.assertEqual(payload['back_urls']['success'], 'https://checkout.tacombinado.net/painel/mensalidade/')
        self.assertEqual(url, self.url)
        self.assertEqual(diagnostics['request']['payload']['items'], payload['items'])
        self.assertNotIn('APP_USR-example', str(diagnostics))
        with patch('tenants.checkout_pro._request') as send_again:
            self.assertEqual(create_checkout(tenant_id=self.tenant.pk, amount=30), self.url)
        send_again.assert_not_called()
        self.assertEqual(PlataformaCheckout.objects.count(), 1)

    def test_payment_is_credited_once_and_allows_next_renewal(self):
        self.create()
        with patch('tenants.checkout_pro._request', return_value=self.payment()):
            approve_payment('789')
            approve_payment('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 11, 14))
        self.assertEqual(PlataformaPagamento.objects.count(), 1)
        self.assertTrue(PlataformaCheckout.objects.get().aprovado)
        self.create()
        self.assertEqual(PlataformaCheckout.objects.count(), 2)

    def test_mismatches_and_unapproved_payments_do_not_credit(self):
        self.create()
        for mismatch in [{'id': 999}, {'collector_id': 999}, {'status': 'pending'},
                         {'status': 'rejected'}, {'currency_id': 'USD'}, {'transaction_amount': 1},
                         {'transaction_amount': 'NaN'}, {'external_reference': 'unrelated'},
                         {'date_approved': None}]:
            with self.subTest(mismatch=mismatch), patch('tenants.checkout_pro._request', return_value=self.payment(**mismatch)):
                approve_payment('789')
        self.assertFalse(PlataformaPagamento.objects.exists())
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 10, 15))

    def test_return_only_credits_verified_payment_for_current_tenant(self):
        self.create()
        self.client.force_login(self.admin)
        with patch('tenants.checkout_pro._request', return_value=self.payment(status='pending')):
            self.client.get('/painel/mensalidade/?payment_id=789&status=approved', HTTP_HOST='checkout.localhost')
        self.assertFalse(PlataformaPagamento.objects.exists())
        with patch('tenants.checkout_pro._request', return_value=self.payment()):
            approve_payment('789', tenant_id=self.tenant.pk + 100)
        self.assertFalse(PlataformaPagamento.objects.exists())
        with patch('tenants.checkout_pro._request', return_value=self.payment()):
            response = self.client.get('/painel/mensalidade/?payment_id=789', HTTP_HOST='checkout.localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlataformaPagamento.objects.count(), 1)

    def test_signed_payment_webhook_and_debug(self):
        self.create()
        manifest = 'id:789;request-id:req;ts:123;'
        signature = hmac.new(b'secret', manifest.encode(), hashlib.sha256).hexdigest()
        with patch('tenants.checkout_pro._request', return_value=self.payment()):
            response = self.client.post('/integracoes/mercado-pago/webhook/?data.id=789&type=payment',
                data=json.dumps({'type': 'payment', 'data': {'id': '789'}}), content_type='application/json',
                HTTP_HOST='checkout.localhost', HTTP_X_REQUEST_ID='req', HTTP_X_SIGNATURE=f'ts=123,v1={signature}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlataformaPagamento.objects.count(), 1)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.mercado_pago_ultimo_webhook['type'], 'payment')

    def test_active_legacy_subscription_is_not_double_billed(self):
        self.tenant.mercado_pago_assinatura_status = 'authorized'
        self.tenant.save()
        with self.assertRaises(MercadoPagoError), patch('tenants.checkout_pro._request') as send:
            create_checkout(tenant_id=self.tenant.pk, amount=30)
        send.assert_not_called()

    def test_pending_legacy_link_is_not_shown(self):
        self.tenant.mercado_pago_assinatura_status = 'pending'
        self.tenant.mercado_pago_checkout_url = 'https://www.mercadopago.com.br/subscriptions/old'
        self.tenant.save()
        self.client.force_login(self.admin)
        page = self.client.get('/painel/mensalidade/', HTTP_HOST='checkout.localhost')
        self.assertNotContains(page, self.tenant.mercado_pago_checkout_url)
        self.assertContains(page, 'Pagar 30 dias com Mercado Pago')

    def test_expired_access_starts_from_payment_date(self):
        self.create()
        Tenant.objects.filter(pk=self.tenant.pk).update(expira_em=date(2026, 1, 1))
        with patch('tenants.checkout_pro._request', return_value=self.payment()):
            approve_payment('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026, 10, 30))

    def test_invalid_signature_never_fetches_payment(self):
        with patch('tenants.checkout_pro._request') as send:
            response = self.client.post('/integracoes/mercado-pago/webhook/?type=payment&data.id=789',
                data='{}', content_type='application/json', HTTP_HOST='checkout.localhost',
                HTTP_X_SIGNATURE='ts=123,v1=bad', HTTP_X_REQUEST_ID='req')
        self.assertEqual(response.status_code, 401)
        send.assert_not_called()

    def test_expired_checkout_replaced_but_late_payment_still_credited(self):
        self.create()
        payment = self.payment()
        PlataformaCheckout.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
        self.create()
        self.assertEqual(PlataformaCheckout.objects.count(), 2)
        with patch('tenants.checkout_pro._request', return_value=payment):
            approve_payment('789')
        self.assertEqual(PlataformaPagamento.objects.count(), 1)

    def test_checkout_rejects_untrusted_url_and_missing_receiver(self):
        for changes in [{'init_point': 'https://evil.example/checkout'}, {'collector_id': None}, {'id': None}]:
            response = {'id': '123-abc', 'collector_id': 456, 'init_point': self.url, **changes}
            with self.subTest(changes=changes), patch('tenants.mercado_pago.urlopen', return_value=FakeResponse(response)):
                with self.assertRaises(MercadoPagoError):
                    create_checkout(tenant_id=self.tenant.pk, amount=30)
            self.assertEqual(PlataformaCheckout.objects.count(), 0)
