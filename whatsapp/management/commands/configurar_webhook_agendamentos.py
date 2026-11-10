from django.core.management.base import BaseCommand, CommandError
from tenants.models import Tenant
from whatsapp import evolution
from whatsapp.webhooks import ensure_webhook


class Command(BaseCommand):
    help = 'Consulta ou configura o webhook autenticado de respostas aos lembretes.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', required=True)
        parser.add_argument('--aplicar', action='store_true', help='Grava a configuração na Evolution API.')

    def handle(self, **options):
        tenant = Tenant.objects.filter(subdomain=options['tenant'], ativo=True).first()
        if not tenant:
            raise CommandError('Estabelecimento ativo não encontrado.')
        try:
            ensure_webhook(tenant, apply=options['aplicar'])
        except evolution.EvolutionError as exc:
            raise CommandError(str(exc)) from None
        if not options['aplicar']:
            self.stdout.write('Consulta concluída. Para configurar, repita com --aplicar. Nenhum segredo foi exibido.')
        else:
            self.stdout.write(self.style.SUCCESS('Webhook configurado. Nenhuma mensagem foi enviada.'))
