import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from tenants.models import Tenant
from .services import criar_checkout


@override_settings(
    PLATFORM_ACCESS_PRICE='30.00', MERCADO_PAGO_ACCESS_TOKEN='test-token',
    MERCADO_PAGO_WEBHOOK_SECRET='test-secret', MERCADO_PAGO_PUBLIC_URL='https://example.test',
    MERCADO_PAGO_LIVE_MODE=False,
)
class OfficialSDKTests(TestCase):
    def test_real_sdk_serializes_preference_and_attaches_credentials(self):
        tenant = Tenant.objects.create(nome='SDK', subdomain='sdk')
        with patch('mercadopago.http.HttpClient.post', return_value={
            'status': 201, 'response': {'id': 'pref', 'collector_id': 123,
                'init_point': 'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref'},
        }) as transport:
            checkout = criar_checkout(tenant_id=tenant.pk, retorno_url='https://sdk.example.test/painel/mensalidade/')
        call = transport.call_args.kwargs
        self.assertEqual(call['url'], 'https://api.mercadopago.com/checkout/preferences')
        self.assertEqual(call['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(call['headers']['x-idempotency-key'], str(checkout.pk))
        self.assertEqual(call['timeout'], 5.0)
        self.assertEqual(call['maxretries'], 0)
        self.assertEqual(json.loads(call['data'])['items'][0]['unit_price'], 30)
