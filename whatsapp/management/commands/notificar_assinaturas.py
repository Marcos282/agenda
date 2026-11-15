from django.core.management.base import BaseCommand
from tenants.models import Tenant
from whatsapp.subscriptions import enviar_aviso_assinatura


class Command(BaseCommand):
    help = 'Envia avisos de assinatura ao telefone de contato dos estabelecimentos.'

    def handle(self, *args, **options):
        enviados = 0
        for tenant_id in Tenant.objects.filter(ativo=True).values_list('pk', flat=True).iterator():
            enviados += bool(enviar_aviso_assinatura(tenant_id))
        self.stdout.write(f'Avisos enviados: {enviados}')
