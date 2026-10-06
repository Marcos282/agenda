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

    def test_individual_blocks_creation_and_activation_but_preserves_inactive(self):
        with self.assertRaises(ValidationError):
            Profissional.objects.create(tenant=self.tenant, nome='Bia')
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Bia', ativo=False)
        inactive.ativo = True
        with self.assertRaises(ValidationError):
            inactive.save()
        self.prof.nome = 'Ana editada'
        self.prof.save()
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant, ativo=True).count(), 1)
        Profissional.objects.create(tenant=self.other, nome='Outra Ana')

    def test_selection_does_not_upgrade_before_payment(self):
        expiry = self.tenant.expira_em
        page = self.choose('PROFISSIONAL', tenant_id=self.other.pk, valor='0.01')
        self.assertContains(page, 'Seu plano atual')
        self.tenant.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.tenant.plano, Tenant.Plano.INDIVIDUAL)
        self.assertEqual(self.tenant.valor_plano, Decimal('30.00'))
        self.assertEqual(self.tenant.expira_em, expiry)
        self.assertEqual(self.other.plano, Tenant.Plano.INDIVIDUAL)
        with self.assertRaises(ValidationError):
            Profissional.objects.create(tenant=self.tenant, nome='Bia')

    def test_downgrade_requires_one_active_and_never_deletes(self):
        self.tenant.plano = 'PROFISSIONAL'
        self.tenant.save(update_fields=['plano'])
        second = Profissional.objects.create(tenant=self.tenant, nome='Bia')
        page = self.choose('INDIVIDUAL')
        self.assertContains(page, 'escolha qual profissional permanecerá ativo')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'PROFISSIONAL')
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant).count(), 2)
        second.ativo = False
        second.save()
        self.choose('INDIVIDUAL')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'PROFISSIONAL')
        self.assertEqual(Profissional.objects.filter(tenant=self.tenant).count(), 2)

    def test_direct_professional_posts_cannot_bypass_limit(self):
        page = self.client.post(reverse('painel:profissional_novo'), {'nome': 'Bia', 'ativo': 'on'}, **self.host)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'apenas um profissional ativo')
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Bia', ativo=False)
        page = self.client.post(reverse('painel:profissional_editar', args=[inactive.pk]), {'nome': 'Bia', 'ativo': 'on'}, **self.host)
        self.assertContains(page, 'apenas um profissional ativo')
        inactive.refresh_from_db()
        self.assertFalse(inactive.ativo)

    def test_invalid_plan_and_other_tenant_admin_are_rejected(self):
        self.choose('30')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plano, 'INDIVIDUAL')
        page = self.client.post(self.url, {'acao': 'escolher_plano', 'plano': 'PROFISSIONAL'}, HTTP_HOST='outro.localhost')
        self.assertEqual(page.status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.plano, 'INDIVIDUAL')

    def test_database_rejects_bulk_creation_activation_and_downgrade(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Profissional.objects.bulk_create([Profissional(tenant=self.tenant, nome='Bia')])
        inactive = Profissional.objects.create(tenant=self.tenant, nome='Bia', ativo=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Profissional.objects.filter(pk=inactive.pk).update(ativo=True)
        self.tenant.plano = 'PROFISSIONAL'
        self.tenant.save(update_fields=['plano'])
        Profissional.objects.filter(pk=inactive.pk).update(ativo=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tenant.objects.filter(pk=self.tenant.pk).update(plano='INDIVIDUAL')

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN='test-token', MERCADO_PAGO_WEBHOOK_SECRET='secret', MERCADO_PAGO_PUBLIC_URL='https://example.test', PLATFORM_ACCESS_PRICE='999')
    def test_checkout_uses_plan_price_and_rejects_old_quote(self):
        first = criar_checkout(tenant_id=self.tenant.pk, retorno_url='https://salao.localhost/painel/mensalidade/', preparar=True)
        self.assertEqual(first.valor, Decimal('30.00'))
        self.assertEqual(first.plano, 'INDIVIDUAL')
        self.tenant.plano = 'PROFISSIONAL'
        self.tenant.save(update_fields=['plano'])
        from pagamentos.services import CheckoutError
        with self.assertRaises(CheckoutError):
            criar_checkout(tenant_id=self.tenant.pk, retorno_url=first.retorno_url, preparar=True, checkout_id=first.pk)
        second = criar_checkout(tenant_id=self.tenant.pk, retorno_url=first.retorno_url, preparar=True)
        self.assertEqual(second.valor, Decimal('50.00'))
        self.assertEqual(second.plano, 'PROFISSIONAL')
        self.assertEqual(CheckoutAcesso.objects.filter(tenant=self.tenant).count(), 2)


class ConcurrentPlanoTests(TransactionTestCase):
    def test_concurrent_activations_only_allow_one_professional(self):
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
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(Profissional.objects.filter(tenant=tenant, ativo=True).count(), 1)


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
        self.assertEqual(Tenant.objects.get(pk=single.pk).plano, 'INDIVIDUAL')
        self.assertEqual(Tenant.objects.get(pk=team.pk).expira_em, date(2027, 1, 15))
        self.assertEqual(Profissional.objects.filter(ativo=True).count(), 3)
        self.assertEqual(Profissional.objects.count(), 4)
