from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from tenants.models import Tenant
from .models import CheckoutAcesso, PagamentoAcesso
from .services import confirmar_pagamento


@override_settings(MERCADO_PAGO_ACCESS_TOKEN='token')
class ConcurrentPaymentTests(TransactionTestCase):
    def test_simultaneous_webhook_and_return_credit_only_once(self):
        tenant = Tenant.objects.create(nome='Concurrent', subdomain='concurrent')
        expiry = tenant.expira_em
        checkout = CheckoutAcesso.objects.create(
            tenant=tenant, valor=Decimal('30'), preferencia_id='preference', recebedor_id='123',
            retorno_url='https://concurrent.example.test/painel/mensalidade/',
            expira_em=timezone.now() + timedelta(days=1),
        )
        barrier = Barrier(2)
        def payment_response(*args):
            barrier.wait(timeout=10)
            return {'status': 200, 'response': {
                'id': 456, 'external_reference': str(checkout.pk), 'transaction_amount': 30,
                'currency_id': 'BRL', 'collector_id': 123, 'live_mode': False,
                'status': 'approved', 'order': {'id': 789},
            }}
        def confirm():
            close_old_connections()
            try:
                return confirmar_pagamento('456').payment_id
            finally:
                close_old_connections()
        with patch('pagamentos.services.mercadopago.SDK') as factory:
            client = factory.return_value
            client.payment.return_value.get.side_effect = payment_response
            client.merchant_order.return_value.get.return_value = {'status': 200, 'response': {'preference_id': 'preference'}}
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(confirm) for _ in range(2)]
                self.assertEqual([f.result(timeout=15) for f in futures], ['456', '456'])
        tenant.refresh_from_db()
        self.assertEqual(tenant.expira_em, expiry + timedelta(days=30))
        self.assertEqual(PagamentoAcesso.objects.count(), 1)
