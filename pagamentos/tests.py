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
        seller_patch = patch('pagamentos.services.consultar_recebedor', return_value={
            'status': 200, 'response': {'id': 456, 'tags': []},
        })
        self.seller = seller_patch.start()
        self.addCleanup(seller_patch.stop)
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

    def enviar_checkout(self, data=None, follow=False):
        data = data or {'acao': 'pagar'}
        preview = self.client.post(self.url, data, **self.host)
        self.assertEqual(preview.status_code, 200)
        return self.client.post(self.url, {**data, 'acao': 'enviar'}, follow=follow, **self.host)

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

    def test_professional_plan_charges_fifty_and_credits_thirty_days(self):
        expiry = self.tenant.expira_em
        checkout = criar_checkout(tenant_id=self.tenant.pk, retorno_url=f'https://marcos.localhost{self.url}', plano='ILIMITADO')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'INDIVIDUAL')
        payload = self.sdk.preference.return_value.create.call_args.args[0]
        self.assertEqual(payload['items'][0]['unit_price'], 50)
        self.assertIn('Plano Profissional', payload['items'][0]['title'])
        self.assertEqual(checkout.plano, 'ILIMITADO')
        self.payment(checkout, transaction_amount=50)
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, expiry + timedelta(days=30))
        self.assertEqual(self.tenant.plano, 'ILIMITADO')

    def test_pending_payment_does_not_change_plan_or_expiration(self):
        expiry = self.tenant.expira_em
        checkout = criar_checkout(tenant_id=self.tenant.pk, retorno_url=f'https://marcos.localhost{self.url}', plano='ILIMITADO')
        self.payment(checkout, transaction_amount=50, status='pending')
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'INDIVIDUAL')
        self.assertEqual(self.tenant.expira_em, expiry)

    def test_confirmed_payment_applies_checkout_plan(self):
        checkout = self.checkout()
        expiry = self.tenant.expira_em
        self.tenant.plano = Tenant.Plano.ILIMITADO
        self.tenant.save(update_fields=['plano'])
        self.payment(checkout)
        confirmar_pagamento('789')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'INDIVIDUAL')
        self.assertEqual(self.tenant.expira_em, expiry + timedelta(days=30))
        checkout.refresh_from_db()
        self.assertEqual(checkout.plano, 'INDIVIDUAL')
        self.assertEqual(checkout.valor, Decimal('30.00'))

    def test_both_plan_buttons_preview_json_then_send_checkout_with_server_price(self):
        for plano, amount in [('ILIMITADO', 50), ('INDIVIDUAL', 30)]:
            with self.subTest(plano=plano):
                response = self.client.post(self.url, {'acao': 'comprar_plano', 'plano': plano,
                    'valor': '0.01', 'tenant_id': self.other.pk}, **self.host)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'painel/checkout_previa.html')
                self.sdk.preference.return_value.create.assert_not_called()
                preview = json.loads(response.context['previa_json'])['requisicao']['corpo']
                self.assertEqual(preview['items'][0]['unit_price'], amount)
                self.assertFalse(CheckoutAcesso.objects.get(pk=self.client.session['checkout_previa']['checkout_id']).preferencia_id)
                response = self.client.post(self.url, {'acao': 'enviar', 'valor': '0.01', 'plano': 'INVALIDO'}, **self.host)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith('https://www.mercadopago.com.br/'))
                payload = self.sdk.preference.return_value.create.call_args.args[0]
                self.assertEqual(payload, preview)
                self.assertEqual(payload['items'][0]['unit_price'], amount)
                self.tenant.refresh_from_db()
                self.other.refresh_from_db()
                self.assertEqual(self.tenant.plano, 'INDIVIDUAL')
                self.assertEqual(self.other.plano, 'INDIVIDUAL')
                self.sdk.preference.return_value.create.reset_mock()

    def test_buy_individual_with_multiple_professionals_cannot_start_checkout(self):
        from profissionais.models import Profissional
        self.tenant.plano = 'ILIMITADO'
        self.tenant.save(update_fields=['plano'])
        for name in ('Ana', 'Bia'):
            Profissional.objects.create(tenant=self.tenant, nome=name)
        page = self.client.post(self.url, {'acao': 'comprar_plano', 'plano': 'INDIVIDUAL'}, follow=True, **self.host)
        self.assertContains(page, 'escolha qual profissional permanecerá ativo')
        self.sdk_class.assert_not_called()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'ILIMITADO')

    def test_checkout_uses_server_price_and_one_off_preference(self):
        response = self.enviar_checkout({'acao': 'pagar', 'valor': '0.01', 'tenant': self.other.pk})
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
        response = self.enviar_checkout({'acao': 'pagar', 'diagnostico': 'checkout'})
        self.assertRedirects(response, CheckoutAcesso.objects.get().checkout_url, fetch_redirect_response=False)

        page = self.client.get(self.url + '?diagnostico=checkout', **self.host)
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
        self.assertContains(page, 'Pagamento aceito')
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
        self.assertNotContains(unverified_page, 'Pagamento aceito')
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
        page = self.client.get(self.url, {'pagamento': notification.payment_id, 'diagnostico': 'checkout'}, **self.host)
        self.assertContains(page, 'Dado bruto do webhook')
        self.assertContains(page, '&quot;type&quot;: &quot;payment&quot;')
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(self.url, {'recebimento': notification.pk}, **self.host).status_code,
            302,
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
        response = self.enviar_checkout(follow=True)
        self.assertContains(response, 'O Mercado Pago não autorizou a operação')
        self.assertNotContains(response, 'seller-token')
        self.assertFalse(CheckoutAcesso.objects.exclude(preferencia_id='').exists())

    def test_provider_403_response_explains_configuration_without_exposing_payload(self):
        self.sdk.preference.return_value.create.return_value = {
            'status': 403, 'response': {'message': 'seller-token', 'error': 'unauthorized'},
        }
        response = self.enviar_checkout(follow=True)
        self.assertContains(response, 'conferir o Access Token')
        self.assertNotContains(response, 'seller-token')
        self.assertFalse(CheckoutAcesso.objects.exclude(preferencia_id='').exists())

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
        self.assertEqual(self.client.post(self.url, {'acao': 'pagar'}, **self.host).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, {'acao': 'pagar'}, HTTP_HOST='wanessa.localhost').status_code, 403)
        self.payment(self.checkout(self.other))
        confirmar_pagamento('789')
        self.assertNotContains(self.client.get(self.url, **self.host), 'Pagamentos recentes')
        self.sdk.payment.return_value.get.reset_mock()
        self.client.get(self.url, **self.host)
        self.sdk.payment.return_value.get.assert_not_called()

    def test_legacy_price_cannot_override_plan_price(self):
        for value in ('NaN', '-1', '0', '30.001', 'Infinity', '9999999'):
            with self.subTest(value=value), self.settings(PLATFORM_ACCESS_PRICE=value):
                self.assertIsNone(preco_acesso())
                self.assertEqual(self.checkout().valor, Decimal('30.00'))

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN='')
    def test_missing_configuration_disables_payments(self):
        response = self.client.post(self.url, {'acao': 'comprar_plano', 'plano': 'ILIMITADO'}, follow=True, **self.host)
        self.assertContains(response, 'O pagamento online ainda não está configurado.')
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

    def test_receipt_selection_persists_on_plain_page_and_is_tenant_scoped(self):
        checkout = self.checkout()
        for payment_id in ('789', '790'):
            self.payment(checkout, id=int(payment_id))
            confirmar_pagamento(payment_id)
        foreign_checkout = self.checkout(self.other)
        self.payment(foreign_checkout, id=791)
        confirmar_pagamento('791')
        page = self.client.get(self.url, **self.host)
        self.assertContains(page, 'Pagamento aceito')
        self.assertContains(page, 'Comprovantes de pagamento')
        self.assertContains(page, 'value="789"')
        self.assertContains(page, 'value="790"')
        self.assertNotContains(page, 'value="791"')
        self.assertNotContains(page, 'id="receipt-details"')
        self.assertNotContains(page, 'Imprimir')
        self.assertIsNone(page.context['comprovante_selecionado'])
        selected = self.client.get(self.url, {'pagamento': '789'}, **self.host)
        self.assertEqual(selected.context['comprovante_selecionado'].pk, '789')
        self.assertContains(selected, 'id="receipt-details"')
        self.assertContains(selected, 'Imprimir')
        self.assertContains(selected, 'sem valor financeiro')
        foreign = self.client.get(self.url, {'pagamento': '791'}, **self.host)
        self.assertIsNone(foreign.context['comprovante_selecionado'])
        self.assertNotContains(foreign, '>791<')

    def test_pending_and_refunded_payments_do_not_offer_receipts_or_accepted_button(self):
        checkout = self.checkout()
        self.payment(checkout, status='pending')
        confirmar_pagamento('789')
        page = self.client.get(self.url, {'status': 'approved'}, **self.host)
        self.assertNotContains(page, 'Pagamento aceito')
        self.assertNotContains(page, 'id="payment-select"')
        self.assertContains(page, 'Ainda não há pagamentos confirmados')
        self.payment(checkout)
        confirmar_pagamento('789')
        self.payment(checkout, status='refunded')
        confirmar_pagamento('789')
        page = self.client.get(self.url, **self.host)
        self.assertNotContains(page, 'Pagamento aceito')
        self.assertNotContains(page, 'id="payment-select"')

    def test_payment_poll_updates_only_for_own_records_without_provider_calls(self):
        original = self.client.get(self.url, {'atualizar': '1'}, **self.host)
        self.assertIn('no-store', original['Cache-Control'])
        self.sdk.payment.return_value.get.assert_not_called()
        other_checkout = self.checkout(self.other)
        self.payment(other_checkout, id=791)
        confirmar_pagamento('791')
        self.assertEqual(self.client.get(self.url, {'atualizar': '1'}, **self.host).json(), original.json())
        self.payment(self.checkout())
        confirmar_pagamento('789')
        self.sdk.payment.return_value.get.reset_mock()
        changed = self.client.get(self.url, {'atualizar': '1'}, **self.host)
        self.assertNotEqual(changed.json()['versao'], original.json()['versao'])
        self.sdk.payment.return_value.get.assert_not_called()
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url, {'atualizar': '1'}, **self.host).status_code, 302)

    def test_return_diagnostic_shows_api_failure_without_granting_days(self):
        checkout = self.checkout()
        original = self.tenant.expira_em
        self.sdk.payment.return_value.get.return_value = {
            'status': 401, 'response': {'status': 401, 'error': 'unauthorized',
                                      'message': 'Unauthorized use of live credentials',
                                      'access_token': 'seller-token'},
        }
        page = self.client.get(self.url, {'checkout': str(checkout.pk),
                                         'payment_id': '789', 'status': 'approved'}, **self.host)
        self.assertContains(page, 'Parâmetros recebidos no retorno (GET)')
        self.assertContains(page, 'Resultado da consulta de confirmação')
        self.assertContains(page, 'Unauthorized use of live credentials')
        self.assertNotContains(page, 'seller-token')
        self.assertNotContains(page, 'Seu prazo de acesso foi atualizado')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, original)

    def test_normal_checkout_saves_diagnostic_and_still_redirects_to_provider(self):
        response = self.enviar_checkout()
        self.assertEqual(response.status_code, 302)
        self.assertIn('mercadopago', response.url)
        checkout = CheckoutAcesso.objects.get(tenant=self.tenant)
        self.payment(checkout)
        page = self.client.get(self.url, {'checkout': str(checkout.pk), 'payment_id': '789'}, **self.host)
        self.assertContains(page, 'JSON enviado e resposta da criação do checkout')
        self.assertContains(page, 'unit_price')
        self.assertContains(page, 'dias_creditados')
        self.assertNotContains(page, 'seller-token')

    def test_webhook_diagnostic_does_not_expose_unverified_or_foreign_ids(self):
        NotificacaoMercadoPago.objects.create(payment_id='999', dado_bruto='PRIVATE_WEBHOOK')
        page = self.client.get(self.url, {'payment_id': '999'}, **self.host)
        self.assertContains(page, 'Nenhum webhook vinculado')
        self.assertNotContains(page, 'PRIVATE_WEBHOOK')

    def test_preview_sends_nothing_and_confirm_sends_exact_displayed_body(self):
        page = self.client.post(self.url, {'acao': 'pagar'}, **self.host)
        self.assertContains(page, 'Conferir JSON antes de enviar')
        self.assertContains(page, 'Enviar ao Mercado Pago')
        self.assertNotContains(page, 'seller-token')
        self.sdk_class.assert_not_called()
        shown = json.loads(page.context['previa_json'])['requisicao']['corpo']
        self.client.post(self.url, {'acao': 'enviar', 'valor': '0.01'}, **self.host)
        sent = self.sdk.preference.return_value.create.call_args.args[0]
        self.assertEqual(shown, sent)

    def test_send_requires_preview_and_rejects_changed_price(self):
        self.client.post(self.url, {'acao': 'enviar'}, **self.host)
        self.sdk_class.assert_not_called()
        self.client.post(self.url, {'acao': 'pagar'}, **self.host)
        session = self.client.session
        session['checkout_previa'] = {**session['checkout_previa'], 'plano': 'ILIMITADO'}
        session.save()
        page = self.client.post(self.url, {'acao': 'enviar'}, follow=True, **self.host)
        self.assertContains(page, 'Confira uma nova prévia')
        self.sdk_class.assert_not_called()

    def test_test_seller_live_mode_true_credits_once_and_preserves_test_receipt(self):
        checkout = self.checkout()
        original = self.tenant.expira_em
        self.payment(checkout, live_mode=True)
        self.seller.return_value = {'status': 200, 'response': {'id': 456, 'tags': ['test_user']}}
        diagnostic = {}
        record = confirmar_pagamento('789', diagnostico=diagnostic)
        confirmar_pagamento('789')
        self.assertIsNotNone(record.creditado_em)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, original + timedelta(days=30))
        self.assertFalse(record.checkout.producao)
        self.assertTrue(diagnostic['verificacao_recebedor']['conta_de_teste'])

    def test_live_mode_exception_rejects_unverified_seller_and_foreign_preference(self):
        checkout = self.checkout()
        self.payment(checkout, live_mode=True)
        for seller in ({'id': 456, 'tags': []}, {'id': 999, 'tags': ['test_user']},
                       {'id': 456, 'tags': 'test_user'}):
            self.seller.return_value = {'status': 200, 'response': seller}
            diagnostic = {}
            self.assertIsNone(confirmar_pagamento('789', diagnostico=diagnostic))
            self.assertIn('motivo_nao_validado', diagnostic)
        self.seller.return_value = {'status': 403, 'response': {}}
        with self.assertRaises(CheckoutError):
            confirmar_pagamento('789')
        self.seller.return_value = {'status': 200, 'response': {'id': 456, 'tags': ['test_user']}}
        self.sdk.merchant_order.return_value.get.return_value['response']['preference_id'] = 'foreign'
        self.assertIsNone(confirmar_pagamento('789'))
        self.assertFalse(PagamentoAcesso.objects.exists())

    def test_production_checkout_rejects_sandbox_payment(self):
        checkout = self.checkout()
        checkout.producao = True
        checkout.save(update_fields=['producao'])
        self.payment(checkout, live_mode=False)
        self.assertIsNone(confirmar_pagamento('789'))
        self.seller.assert_not_called()
