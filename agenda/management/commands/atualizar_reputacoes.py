from django.core.management.base import BaseCommand
from tenants.models import Tenant
from agenda.reputation import atualizar_reputacoes


class Command(BaseCommand):
    help = 'Registra avaliações pendentes de atendimentos encerrados, cancelados e ausências.'

    def handle(self, *args, **options):
        for tenant in Tenant.objects.all().iterator():
            atualizar_reputacoes(tenant)
        self.stdout.write(self.style.SUCCESS('Reputações atualizadas sem duplicar avaliações.'))
