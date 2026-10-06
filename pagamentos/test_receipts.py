from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from pagamentos.models import CheckoutAcesso, PagamentoAcesso
from pagamentos.services import confirmar_pagamento, criar_checkout, CheckoutError
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User


@override_settings(DEBUG=True, TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['localhost', '.localhost', 'tacombinado.net'],
    MERCADO_PAGO_ACCESS_TOKEN='server-secret-token', MERCADO_PAGO_WEBHOOK_SECRET='webhook-secret',
    MERCADO_PAGO_PUBLIC_URL='https://tacombinado.net', MERCADO_PAGO_LIVE_MODE=False,
    DEV_PUBLIC_HOST='', DEV_TENANT_SUBDOMAIN='')
class ReceiptTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Marcos', subdomain='marcos', expira_em=date(2026, 11, 5))
        self.other = Tenant.objects.create(nome='Outra', subdomain='outra')
        self.admin = User.objects.create_user('receipts@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.host = {'HTTP_HOST': 'marcos.localhost'}
        self.checkout = CheckoutAcesso.objects.create(tenant=self.tenant, plano='PROFISSIONAL', valor=Decimal('50'),
            preferencia_id='preference', recebedor_id='123', retorno_url='https://marcos.localhost/painel/mensalidade/', expira_em=timezone.now()+timedelta(days=1))
        factory = patch('pagamentos.services.mercadopago.SDK')
        self.sdk = factory.start().return_value
        self.addCleanup(factory.stop)
        self.sdk.payment.return_value.get.return_value = {'status':200, 'response':{
            'id':789, 'status':'approved', 'external_reference':str(self.checkout.pk),
            'transaction_amount':50, 'currency_id':'BRL', 'collector_id':123,
            'live_mode':False, 'order':{'id':999}, 'date_approved':'2026-10-06T16:00:00Z',
        }}
        self.sdk.merchant_order.return_value.get.return_value={'status':200, 'response':{'preference_id':'preference'}}

    def approve(self):
        with patch('django.utils.timezone.localdate', return_value=date(2026,10,6)):
            return confirmar_pagamento('789')

    def test_approved_snapshot_and_receipt_are_idempotent(self):
        record = self.approve()
        self.assertEqual(record.validade_anterior, date(2026,11,5))
        self.assertEqual(record.nova_validade, date(2026,12,5))
        self.assertEqual(record.dias_concedidos, 30)
        self.assertEqual(record.aprovado_em.isoformat(), '2026-10-06T16:00:00+00:00')
        self.approve()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.expira_em, date(2026,12,5))
        self.assertEqual(self.tenant.plano,'PROFISSIONAL')
        url=reverse('painel:comprovante_pagamento',args=['789'])
        page=self.client.get(url, {'valor':'0.01', 'nova_validade':'2099-01-01'}, **self.host)
        for text in ('Plano Profissional','50,00','05/11/2026','05/12/2026','Pagamento aprovado'):
            self.assertContains(page,text)
        self.assertNotContains(page,'2099')
        self.assertNotContains(page,'server-secret-token')
        self.assertContains(self.client.get(reverse('painel:mensalidade'),**self.host),url)

    def test_expired_subscription_counts_from_today(self):
        self.tenant.expira_em=date(2026,9,1)
        self.tenant.save(update_fields=['expira_em'])
        record=self.approve()
        self.assertEqual(record.validade_anterior,date(2026,9,1))
        self.assertEqual(record.nova_validade,date(2026,11,5))

    def test_pending_and_foreign_payment_have_no_receipt(self):
        self.sdk.payment.return_value.get.return_value['response']['status']='pending'
        self.approve()
        url=reverse('painel:comprovante_pagamento',args=['789'])
        self.assertEqual(self.client.get(url,**self.host).status_code,404)
        self.assertNotContains(self.client.get(reverse('painel:mensalidade'),**self.host), 'billing-receipt-button')
        self.sdk.payment.return_value.get.return_value['response']['status']='approved'
        self.approve()
        other_admin=User.objects.create_user('other-admin@example.test',tenant=self.other,tipo='ADMIN')
        self.client.force_login(other_admin)
        self.assertEqual(self.client.get(url,HTTP_HOST='outra.localhost').status_code,404)

    def test_central_return_ignores_forged_success_and_uses_internal_tenant(self):
        self.client.logout()
        page=self.client.get(reverse('mercado_pago_sucesso'),{'external_reference':str(self.checkout.pk),'status':'approved','payment_id':'789','next':'https://evil.test'},HTTP_HOST='localhost')
        self.assertEqual(page.status_code,302)
        self.assertTrue(page.url.startswith('https://marcos.localhost/painel/mensalidade/?checkout='))
        self.sdk.payment.return_value.get.assert_not_called()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano,'INDIVIDUAL')
        self.assertFalse(PagamentoAcesso.objects.exists())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('mercado_pago_pendente'),{'external_reference':str(self.checkout.pk)},HTTP_HOST='localhost').status_code,302)
        foreign=CheckoutAcesso.objects.create(tenant=self.other,valor=30,retorno_url='https://outra.localhost',expira_em=timezone.now()+timedelta(days=1))
        self.assertEqual(self.client.get(reverse('mercado_pago_sucesso'),{'external_reference':str(foreign.pk)},HTTP_HOST='localhost').status_code,403)

    def test_preference_has_central_https_endpoints(self):
        checkout=criar_checkout(tenant_id=self.tenant.pk,retorno_url=self.checkout.retorno_url,preparar=True)
        diagnostics={}
        criar_checkout(tenant_id=self.tenant.pk,retorno_url=self.checkout.retorno_url,preparar=True,diagnostico=diagnostics)
        payload=diagnostics['requisicao']['corpo']
        self.assertEqual(payload['notification_url'],'https://tacombinado.net/pagamentos/mercadopago/webhook/')
        for state,name in [('success','sucesso'),('pending','pendente'),('failure','falha')]:
            self.assertEqual(payload['back_urls'][state],f'https://tacombinado.net/pagamentos/mercadopago/{name}/')
        self.assertEqual(payload['external_reference'],str(checkout.pk))
        self.assertNotIn('server-secret-token',str(payload))

    def test_downgrade_rechecks_professionals_at_confirmation(self):
        self.tenant.plano='PROFISSIONAL'
        self.tenant.save(update_fields=['plano'])
        self.checkout.plano='INDIVIDUAL'
        self.checkout.valor=30
        self.checkout.save(update_fields=['plano','valor'])
        self.sdk.payment.return_value.get.return_value['response']['transaction_amount']=30
        for name in ['Ana','Bia']:
            Profissional.objects.create(tenant=self.tenant,nome=name)
        with self.assertRaises(CheckoutError):
            self.approve()
        self.assertFalse(PagamentoAcesso.objects.filter(creditado_em__isnull=False).exists())
        second=Profissional.objects.filter(tenant=self.tenant).last()
        second.ativo=False
        second.save()
        self.approve()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano,'INDIVIDUAL')
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant).count(),2)
