from datetime import timedelta
from decimal import Decimal
import hashlib
import hmac
import json
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from mercadopago.errors.exceptions import MPAuthenticationError
from requests.exceptions import Timeout

from tenants.models import Tenant
from usuarios.models import User
from .models import CheckoutAcesso, NotificacaoMercadoPago, PagamentoAcesso
from .services import CheckoutError, confirmar_pagamento, criar_checkout, preco_acesso


@override_settings(
    TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost', 'localhost', 'checkout.ngrok-free.dev'],
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='', PLATFORM_ACCESS_PRICE='30.00',
    MERCADO_PAGO_ACCESS_TOKEN='seller-token', MERCADO_PAGO_WEBHOOK_SECRET='webhook-secret',
    MERCADO_PAGO_PUBLIC_URL='https://checkout.ngrok-free.dev', MERCADO_PAGO_LIVE_MODE=False,
)
class CheckoutProTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos')
        cls.other = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        cls.admin = User.objects.create_user('owner@example.test', tenant=cls.tenant, tipo='ADMIN')
        cls.customer = User.objects.create_user('customer@example.test', tenant=cls.tenant)

    def setUp(self):
        self.client.force_login(self.admin)
        self.host = {'HTTP_HOST': 'marcos.localhost'}
        self.url = reverse('painel:mensalidade')
        self.patcher = patch('pagamentos.services.mercadopago.SDK')
        self.sdk_class = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.sdk = self.sdk_class.return_value
        self.sdk.preference.return_value.create.return_value = {'status': 201, 'response': {
            'id': 'preference-123', 'collector_id': 456,
            'init_point': 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=preference-123',
        }}
        self.sdk.merchant_order.return_value.get.return_value = {
            'status': 200, 'response': {'id': 999, 'preference_id': 'preference-123'},
        }

    def checkout(self, tenant=None):
        tenant = tenant or self.tenant
        return criar_checkout(tenant_id=tenant.pk, retorno_url=f'https://{tenant.subdomain}.localhost{self.url}')

    def payment(self, checkout, **changes):
        data = {'id': 789, 'external_reference': str(checkout.pk), 'transaction_amount': 30,
                'currency_id': 'BRL', 'collector_id': 456, 'live_mode': False,
                'status': 'approved', 'order': {'id': 999, 'type': 'mercadopago'}}
        data.update(changes)
        self.sdk.payment.return_value.get.return_value = {'status': 200, 'response': data}
        return data

    def webhook(self, *, signature=True, body_id='789', body_type='payment'):
        # Sign independently; the application uses the actual official SDK validator.
        manifest = 'id:789;request-id:request-1;ts:1742505638683;'
        digest = hmac.new(b'webhook-secret', manifest.encode(), hashlib.sha256).hexdigest()
        return Client(enforce_csrf_checks=True).post(
            reverse('mercado_pago_webhook') + '?data.id=789&type=payment',
            data={'type': body_type, 'data': {'id': body_id}}, content_type='application/json',
            HTTP_HOST='localhost', HTTP_X_REQUEST_ID='request-1',
            HTTP_X_SIGNATURE=f'ts=1742505638683,v1={digest}' if signature else 'invalid',
        )

    def test_checkout_uses_server_price_and_one_off_preference(self):
        response = self.client.post(self.url, {'acao': 'pagar', 'valor': '0.01', 'tenant': self.other.pk}, **self.host)
        checkout = CheckoutAcesso.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, checkout.checkout_url)
        self.assertEqual(checkout.tenant_id, self.tenant.pk)
        payload, options = self.sdk.preference.return_value.create.call_args.args
        self.assertEqual(payload['items'][0]['unit_price'], 30)
        self.assertEqual(payload['external_reference'], str(checkout.pk))
        self.assertEqual(payload['back_urls']['success'], f'https://marcos.localhost{self.url}?checkout={checkout.pk}')
        self.assertNotIn('payer', payload)
        self.assertNotIn('auto_recurring', payload)
        self.sdk.preapproval.assert_not_called()
        self.assertEqual(options.custom_headers['x-idempotency-key'], str(checkout.pk))
        self.assertEqual(options.connection_timeout, 5.0)
        self.assertEqual(options.max_retries, 0)

    def test_opt_in_checkout_diagnostic_is_admin_only_and_redacted(self):
        self.sdk.preference.return_value.create.return_value['response'].update({
            'payer_email': 'buyer@example.test',
            'access_token': 'must-not-be-rendered',
            'sandbox_init_point': 'https://sandbox.mercadopago.com/checkout?secret=value',
        })
        response = self.client.post(
            self.url, {'acao': 'pagar', 'diagnostico': 'checkout'}, **self.host,
        )
        self.assertRedirects(response, f'{self.url}?diagnostico=checkout', fetch_redirect_response=False)

        page = self.client.get(response.url, **self.host)
        self.assertContains(page, 'Diagnóstico temporário do Checkout Pro')
        self.assertContains(page, 'preferencia_criada')
        self.assertContains(page, 'status_http')
        self.assertContains(page, 'sandbox.mercadopago.com')
        self.assertNotContains(page, 'buyer@example.test')
        self.assertNotContains(page, 'must-not-be-rendered')
        self.assertNotContains(page, 'Authorization')
        self.assertNotContains(page, '?secret=value')

    def test_repeated_click_reuses_checkout_but_paid_or_expired_creates_another(self):
        first = self.checkout()
        self.assertEqual(self.checkout().pk, first.pk)
        self.assertEqual(self.sdk.preference.return_value.create.call_count, 1)
        self.payment(first)
        confirmar_pagamento('789')
        second = self.checkout()
        self.assertNotEqual(first.pk, second.pk)
        CheckoutAcesso.objects.filter(pk=second.pk).update(expira_em=timezone.now() - timedelta(seconds=1))
        self.assertNotEqual(second.pk, self.checkout().pk)

    def test_approved_payment_adds_thirty_days_only_once(self):
        original = self.tenant.expira_em
        checkout = self.checkout()
        self.payment(checkout)
        self.assertEqual(self.webhook().status_code, 200)
        self.assertEqual(self.webhook().status_code, 200)
        page = self.client.get(
            self.url, {'checkout': checkout.pk, 'payment_id': '789', 'status': 'approved'}, **self.host,
        )
        self.assertContains(page, 'PAGAMENTO RECEBIDO')
        self.assertContains(page, 'name="pagamento"')
        self.assertContains(page, 'value="789"')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, original + timedelta(days=30))
        self.assertEqual(PagamentoAcesso.objects.count(), 1)
        self.assertIsNotNone(PagamentoAcesso.objects.get().creditado_em)

    def test_expired_access_restarts_from_today(self):
        self.tenant.expira_em = timezone.localdate() - timedelta(days=10)
        self.tenant.save()
        self.payment(self.checkout())
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, timezone.localdate() + timedelta(days=30))

    def test_two_distinct_payments_each_credit_thirty_days(self):
        original = self.tenant.expira_em
        checkout = self.checkout()
        for payment_id in ('789', '790'):
            self.payment(checkout, id=int(payment_id))
            confirmar_pagamento(payment_id)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, original + timedelta(days=60))

    def test_pending_then_approved_and_late_notification(self):
        checkout = self.checkout()
        original = self.tenant.expira_em
        self.payment(checkout, status='pending')
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, original)
        self.assertIsNone(PagamentoAcesso.objects.get().creditado_em)
        CheckoutAcesso.objects.filter(pk=checkout.pk).update(expira_em=timezone.now() - timedelta(days=2))
        self.payment(checkout)
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, original + timedelta(days=30))

    def test_untrusted_status_or_other_tenant_return_cannot_grant_access(self):
        other_checkout = self.checkout(self.other)
        self.payment(other_checkout)
        page = self.client.get(self.url, {'checkout': other_checkout.pk, 'payment_id': '789', 'status': 'approved'}, **self.host)
        self.sdk.payment.return_value.get.assert_not_called()
        self.assertNotContains(page, 'Pagamento aprovado')
        own_checkout = self.checkout()
        unverified_page = self.client.get(
            self.url, {'checkout': own_checkout.pk, 'payment_id': '789', 'status': 'approved'}, **self.host,
        )
        self.assertNotContains(unverified_page, 'PAGAMENTO RECEBIDO')
        self.assertFalse(PagamentoAcesso.objects.exists())
        self.client.get(self.url, {'status': 'approved'}, **self.host)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, self.tenant.data_expiracao)

    def test_mismatched_payment_details_never_credit(self):
        checkout = self.checkout()
        for changes in [
            {'id': 790}, {'transaction_amount': 1}, {'transaction_amount': 'NaN'},
            {'currency_id': 'USD'}, {'collector_id': 457}, {'live_mode': True},
            {'external_reference': str(uuid4())}, {'external_reference': 'invalid'},
            {'status': 'unknown'}, {'order': {}}, {'transaction_amount_refunded': 1},
        ]:
            with self.subTest(changes=changes):
                self.payment(checkout, **changes)
                self.assertIsNone(confirmar_pagamento('789'))
        self.assertFalse(PagamentoAcesso.objects.exists())
        self.payment(checkout)
        self.sdk.merchant_order.return_value.get.return_value['response']['preference_id'] = 'other'
        self.assertIsNone(confirmar_pagamento('789'))

    def test_signature_body_and_api_errors(self):
        self.payment(self.checkout())
        self.assertEqual(self.webhook(signature=False).status_code, 401)
        self.assertFalse(NotificacaoMercadoPago.objects.exists())
        self.assertEqual(self.webhook(body_id='790').status_code, 400)
        self.assertEqual(self.webhook(body_type='subscription_preapproval').status_code, 200)
        self.sdk.payment.return_value.get.assert_not_called()
        ignored = NotificacaoMercadoPago.objects.get()
        self.assertEqual(ignored.estado, NotificacaoMercadoPago.Estado.IGNORADA)
        self.sdk.payment.return_value.get.side_effect = Timeout('do-not-expose')
        response = self.webhook()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'do-not-expose', response.content)
        self.assertFalse(PagamentoAcesso.objects.exists())
        retry = NotificacaoMercadoPago.objects.latest('recebido_em')
        self.assertEqual(retry.estado, NotificacaoMercadoPago.Estado.AGUARDANDO_REENVIO)

    def test_valid_webhook_is_stored_and_visible_only_to_its_tenant(self):
        checkout = self.checkout()
        self.payment(checkout)
        response = self.webhook()
        self.assertEqual(response.status_code, 200)
        notification = NotificacaoMercadoPago.objects.get()
        self.assertEqual(notification.payment_id, '789')
        self.assertEqual(notification.estado, NotificacaoMercadoPago.Estado.PROCESSADA)
        self.assertEqual(notification.pagamento_id, '789')
        self.assertEqual(json.loads(notification.dado_bruto)['data']['id'], '789')
        self.assertNotIn('x-signature', notification.dado_bruto)

        page = self.client.get(self.url, {'pagamento': notification.payment_id}, **self.host)
        self.assertContains(page, 'Dado bruto do webhook')
        self.assertContains(page, '&quot;type&quot;: &quot;payment&quot;')
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(self.url, {'recebimento': notification.pk}, **self.host).status_code,
            403,
        )

    def test_malformed_webhook_is_rejected(self):
        response = Client().post(reverse('mercado_pago_webhook'), data='[]', content_type='application/json', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 400)
        self.sdk.payment.return_value.get.assert_not_called()

    def test_invalid_ids_never_reach_provider(self):
        for value in ('../123', '123?foo=1', '', 'x'*101, '１２３'):
            self.assertIsNone(confirmar_pagamento(value))
        self.sdk.payment.return_value.get.assert_not_called()

    def test_provider_failure_does_not_leave_checkout_or_leak_secrets(self):
        self.sdk.preference.return_value.create.side_effect = MPAuthenticationError(401, {'message': 'seller-token'})
        response = self.client.post(self.url, {'acao': 'pagar'}, follow=True, **self.host)
        self.assertContains(response, 'O Mercado Pago não autorizou a operação')
        self.assertNotContains(response, 'seller-token')
        self.assertFalse(CheckoutAcesso.objects.exists())

    def test_provider_403_response_explains_configuration_without_exposing_payload(self):
        self.sdk.preference.return_value.create.return_value = {
            'status': 403, 'response': {'message': 'seller-token', 'error': 'unauthorized'},
        }
        response = self.client.post(self.url, {'acao': 'pagar'}, follow=True, **self.host)
        self.assertContains(response, 'conferir o Access Token')
        self.assertNotContains(response, 'seller-token')
        self.assertFalse(CheckoutAcesso.objects.exists())

    def test_invalid_redirect_is_rejected(self):
        for value in ('https://mercadopago.com.br.evil.test/x', 'javascript:alert(1)', 'https://evil.test', None):
            with self.subTest(url=value):
                self.sdk.preference.return_value.create.return_value['response']['init_point'] = value
                with self.assertRaises(CheckoutError):
                    self.checkout()
        self.assertFalse(CheckoutAcesso.objects.exists())

    def test_permissions_csrf_and_tenant_history(self):
        self.assertEqual(Client(enforce_csrf_checks=True).get(self.url, **self.host).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, {'acao': 'pagar'}, **self.host).status_code, 403)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(self.url, {'acao': 'pagar'}, **self.host).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, {'acao': 'pagar'}, HTTP_HOST='wanessa.localhost').status_code, 403)
        self.payment(self.checkout(self.other))
        confirmar_pagamento('789')
        self.assertNotContains(self.client.get(self.url, **self.host), 'Pagamentos recentes')
        self.sdk.payment.return_value.get.reset_mock()
        self.client.get(self.url, **self.host)
        self.sdk.payment.return_value.get.assert_not_called()

    def test_invalid_price_disables_checkout(self):
        for value in ('NaN', '-1', '0', '30.001', 'Infinity', '9999999'):
            with self.subTest(value=value), self.settings(PLATFORM_ACCESS_PRICE=value):
                self.assertIsNone(preco_acesso())
                with self.assertRaises(CheckoutError):
                    self.checkout()
        self.sdk.preference.return_value.create.assert_not_called()

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN='')
    def test_missing_configuration_disables_payments(self):
        response = self.client.post(self.url, {'acao': 'pagar'}, follow=True, **self.host)
        self.assertContains(response, 'Pagamento ainda indisponível')
        self.sdk.preference.return_value.create.assert_not_called()

    @override_settings(DEBUG=True, DEV_PUBLIC_HOST='checkout.ngrok-free.dev', DEV_TENANT_SUBDOMAIN='marcos')
    def test_ngrok_selects_explicit_tenant_and_generates_https_return(self):
        self.assertEqual(self.client.get(self.url, HTTP_HOST='checkout.ngrok-free.dev').status_code, 200)
        self.client.post(self.url, {'acao': 'pagar'}, HTTP_HOST='checkout.ngrok-free.dev')
        checkout = CheckoutAcesso.objects.get()
        self.assertEqual(checkout.tenant_id, self.tenant.pk)
        self.assertEqual(checkout.retorno_url, 'https://checkout.ngrok-free.dev' + self.url)
        with self.settings(DEBUG=False):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='checkout.ngrok-free.dev').status_code, 404)

    def test_refund_is_recorded_without_duplicate_credit(self):
        checkout = self.checkout()
        self.payment(checkout)
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        expiry = self.tenant.expira_em
        self.payment(checkout, status='refunded')
        record = confirmar_pagamento('789')
        self.assertEqual(record.status, 'refunded')
        self.assertIsNotNone(record.creditado_em)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, expiry)
