from django.core.management.base import BaseCommand, CommandError
from whatsapp.evolution import configured
from whatsapp.reminders import process_reminders


class Command(BaseCommand):
    help = 'Envia os lembretes pendentes. Execute a cada minuto pelo agendador do servidor.'

    def handle(self, **options):
        if not configured():
            raise CommandError('Configure EVOLUTION_API_URL e EVOLUTION_API_KEY no ambiente do processo.')
        self.stdout.write(f'Lembretes aceitos pela API: {process_reminders()}')
