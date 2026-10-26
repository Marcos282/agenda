from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from pagamentos.models import CheckoutAcesso
from pagamentos.services import criar_checkout
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User


@override_settings(TENANT_BASE_DOMAIN='localhost', ALLOWED_HOSTS=['.localhost', 'localhost'], MERCADO_PAGO_ACCESS_TOKEN='', MERCADO_PAGO_WEBHOOK_SECRET='')
class PlanoTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(nome='Salão', subdomain='salao')
        self.other = Tenant.objects.create(nome='Outro', subdomain='outro')
        self.prof = Profissional.objects.create(tenant=self.tenant, nome='Ana')
        self.admin = User.objects.create_user('planos@example.test', tenant=self.tenant, tipo='ADMIN')
        self.client.force_login(self.admin)
        self.host = {'HTTP_HOST': 'salao.localhost'}
        self.url = reverse('painel:mensalidade')

    def choose(self, plano, **extra):
        return self.client.post(self.url, {'acao': 'escolher_plano', 'plano': plano, **extra}, follow=True, **self.host)

    def test_unlimited_creation_and_activation_preserves_inactive(self):
        Profissional.objects.create(tenant=self.tenant, nome='Bia')
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Bia', ativo=False)
        inactive.ativo = True
        inactive.save()
        self.prof.nome = 'Ana editada'
        self.prof.save()
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant, ativo=True).count(), 3)
        Profissional.objects.create(tenant=self.other, nome='Outra Ana')

    def test_selection_does_not_upgrade_before_payment(self):
        expiry = self.tenant.expira_em
        page = self.choose('PROFISSIONAL', tenant_id=self.other.pk, valor='0.01')
        self.assertContains(page, 'Seu plano atual')
        self.tenant.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.tenant.plano, Tenant.Plano.PROFISSIONAL)
        self.assertEqual(self.tenant.valor_plano, Decimal('30.00'))
        self.assertEqual(self.tenant.expira_em, expiry)
        self.assertEqual(self.other.plano, Tenant.Plano.PROFISSIONAL)
        Profissional.objects.create(tenant=self.tenant, nome='Bia')

    def test_legacy_plan_selection_is_rejected_and_never_deletes(self):
        self.tenant.plano = 'PROFISSIONAL'
        self.tenant.save(update_fields=['plano'])
        second = Profissional.objects.create(tenant=self.tenant, nome='Bia')
        page = self.choose('INDIVIDUAL')
        self.assertContains(page, 'Escolha um plano válido.')
        self.assertNotContains(page, 'escolha qual profissional permanecerá ativo')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'PROFISSIONAL')
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant).count(), 2)
        second.ativo = False
        second.save()
        self.choose('INDIVIDUAL')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'PROFISSIONAL')
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant).count(), 2)

    def test_direct_professional_posts_allow_unlimited_creation_and_activation(self):
        page = self.client.post(reverse('painel:profissional_novo'), {'nome': 'Bia', 'ativo': 'on'}, **self.host)
        self.assertEqual(page.status_code, 302)
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Bia', ativo=False)
        page = self.client.post(reverse('painel:profissional_editar', args=[inactive.pk]), {'nome': 'Bia', 'ativo': 'on'}, **self.host)
        self.assertEqual(page.status_code, 302)
        inactive.refresh_from_db()
        self.assertTrue(inactive.ativo)

    def test_invalid_plan_and_other_tenant_admin_are_rejected(self):
        self.choose('30')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'PROFISSIONAL')
        page = self.client.post(self.url, {'acao': 'escolher_plano', 'plano': 'PROFISSIONAL'}, HTTP_HOST='outro.localhost')
        self.assertEqual(page.status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.plano, 'PROFISSIONAL')

    def test_database_allows_bulk_professionals_but_rejects_legacy_plan(self):
        Profissional.objects.bulk_create([Profissional(tenant=self.tenant, nome='Bia')])
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Bia', ativo=False)
        Profissional.objects.filter(pk=inactive.pk).update(ativo=True)
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant, ativo=True).count(), 3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tenant.objects.filter(pk=self.tenant.pk).update(plano='INDIVIDUAL')
        self.tenant.plano = 'INDIVIDUAL'
        with self.assertRaises(ValidationError):
            self.tenant.save()

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN='test-token', MERCADO_PAGO_WEBHOOK_SECRET='secret', MERCADO_PAGO_PUBLIC_URL='https://example.test', PLATFORM_ACCESS_PRICE='999', PLATFORM_MONTHLY_PRICE='30.00')
    def test_checkout_uses_plan_price_and_rejects_old_quote(self):
        first = criar_checkout(tenant_id=self.tenant.pk, retorno_url='https://salao.localhost/painel/mensalidade/', preparar=True)
        self.assertEqual(first.valor, Decimal('30.00'))
        self.assertEqual(first.plano, 'PROFISSIONAL')
        from pagamentos.services import CheckoutError
        reused = criar_checkout(tenant_id=self.tenant.pk, retorno_url=first.retorno_url, preparar=True)
        self.assertEqual(first.pk, reused.pk)
        with self.settings(PLATFORM_MONTHLY_PRICE='35.90'):
            with self.assertRaises(CheckoutError):
                criar_checkout(tenant_id=self.tenant.pk, retorno_url=first.retorno_url, preparar=True, checkout_id=first.pk)
            second = criar_checkout(tenant_id=self.tenant.pk, retorno_url=first.retorno_url, preparar=True)
        self.assertEqual(second.valor, Decimal('35.90'))
        self.assertEqual(second.plano, 'PROFISSIONAL')
        self.assertEqual(CheckoutAcesso.objects.filter(tenant=self.tenant).count(), 2)


class ConcurrentPlanoTests(TransactionTestCase):
    def test_concurrent_activations_allow_all_professionals(self):
        tenant = Tenant.objects.create(nome='Concorrência', subdomain='concorrencia')
        professionals = [Profissional.objects.create(tenant=tenant, nome=str(i), ativo=False) for i in range(2)]
        barrier = Barrier(2)

        def activate(pk):
            close_old_connections()
            try:
                prof = Profissional.objects.get(pk=pk)
                prof.ativo = True
                barrier.wait(timeout=10)
                try:
                    prof.save()
                    return True
                except ValidationError:
                    return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(activate, [p.pk for p in professionals]))
        self.assertEqual(results, [True, True])
        self.assertEqual(Profissional.objects.filter(tenant=tenant, ativo=True).count(), 2)


class PlanoMigrationTests(TransactionTestCase):
    def test_migration_preserves_existing_teams_and_validity(self):
        from datetime import date
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [('tenants', '0011_tenant_limite_agendamentos_cliente_futuros'), ('profissionais', '0001_initial')]
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            OldTenant = apps.get_model('tenants', 'Tenant')
            OldProfissional = apps.get_model('profissionais', 'Profissional')
            team = OldTenant.objects.create(nome='Equipe', subdomain='equipe', expira_em=date(2027, 1, 15))
            single = OldTenant.objects.create(nome='Individual', subdomain='individual')
            OldProfissional.objects.bulk_create([
                OldProfissional(tenant=team, nome='Ana'), OldProfissional(tenant=team, nome='Bia'),
                OldProfissional(tenant=single, nome='Cris'), OldProfissional(tenant=single, nome='Duda', ativo=False),
            ])
        finally:
            MigrationExecutor(connection).migrate(latest)
        self.assertEqual(Tenant.objects.get(pk=team.pk).plano, 'PROFISSIONAL')
        self.assertEqual(Tenant.objects.get(pk=single.pk).plano, 'PROFISSIONAL')
        self.assertEqual(Tenant.objects.get(pk=team.pk).expira_em, date(2027, 1, 15))
        self.assertEqual(Profissional.objects.filter(ativo=True).count(), 3)
        self.assertEqual(Profissional.objects.count(), 4)

    def test_single_plan_migration_changes_only_plan_without_billing(self):
        from datetime import date, timedelta
        from importlib import import_module
        from unittest.mock import patch
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from django.utils import timezone

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [
            ('tenants', '0020_image_visibility') if app == 'tenants' else
            ('pagamentos', '0004_remove_checkoutacesso_checkout_acesso_plano_valido_and_more') if app == 'pagamentos' else
            (app, name) for app, name in latest
        ]
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            OldTenant = apps.get_model('tenants', 'Tenant')
            OldCheckout = apps.get_model('pagamentos', 'CheckoutAcesso')
            OldPayment = apps.get_model('pagamentos', 'PagamentoAcesso')
            OldProfessional = apps.get_model('profissionais', 'Profissional')
            for index, (plano, ativo) in enumerate([
                ('INDIVIDUAL', True), ('INDIVIDUAL', False), ('PROFISSIONAL', True),
            ]):
                tenant = OldTenant.objects.create(
                    nome=f'Legado {index}', subdomain=f'legado-{index}', plano=plano,
                    ativo=ativo, expira_em=date(2027, 1, 15),
                )
                OldProfessional.objects.create(tenant=tenant, nome='Ana', ativo=True)
                checkout = OldCheckout.objects.create(
                    tenant=tenant, plano=plano, valor=30 if plano == 'INDIVIDUAL' else 50,
                    preferencia_id=f'pref-{index}', recebedor_id='123',
                    checkout_url='https://www.mercadopago.com.br/checkout',
                    retorno_url='https://example.test', expira_em=timezone.now() + timedelta(days=1),
                )
                OldPayment.objects.create(
                    payment_id=str(100 + index), checkout=checkout, status='approved',
                    creditado_em=timezone.now(), aprovado_em=timezone.now(),
                    validade_anterior=date(2026, 12, 16), nova_validade=tenant.expira_em,
                    dias_concedidos=30,
                )
                pending = OldCheckout.objects.create(
                    tenant=tenant, plano=plano, valor=checkout.valor,
                    retorno_url='https://example.test', expira_em=checkout.expira_em,
                )
                OldPayment.objects.create(payment_id=str(200 + index), checkout=pending, status='pending')
            tenant_snapshot = list(OldTenant.objects.order_by('pk').values())
            checkout_snapshot = list(OldCheckout.objects.order_by('pk').values())
            payment_snapshot = list(OldPayment.objects.order_by('pk').values())
            professional_snapshot = list(OldProfessional.objects.order_by('pk').values())
            with patch('pagamentos.services.mercadopago.SDK') as sdk:
                executor.migrate(latest)
                new_apps = executor.loader.project_state(latest).apps
                with connection.schema_editor() as schema_editor:
                    migration = import_module('tenants.migrations.0021_plano_unico')
                    migration.unificar_planos(new_apps, schema_editor)
                sdk.assert_not_called()
            for row in tenant_snapshot:
                row['plano'] = 'PROFISSIONAL'
            self.assertEqual(list(Tenant.objects.order_by('pk').values()), tenant_snapshot)
            self.assertEqual(list(CheckoutAcesso.objects.order_by('pk').values()), checkout_snapshot)
            from pagamentos.models import PagamentoAcesso
            self.assertEqual(list(PagamentoAcesso.objects.order_by('pk').values()), payment_snapshot)
            self.assertEqual(list(Profissional.objects.order_by('pk').values()), professional_snapshot)
            for tenant in Tenant.objects.all():
                Profissional.objects.create(tenant=tenant, nome='Bia')
        finally:
            MigrationExecutor(connection).migrate(latest)
