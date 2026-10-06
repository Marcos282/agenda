from django.core.management.base import BaseCommand
from whatsapp.returns import processar_retornos


class Command(BaseCommand):
    help = 'Processa lembretes de retorno após 30 dias do último atendimento concluído. Execute diariamente.'

    def handle(self, **options):
        counts = processar_retornos()
        self.stdout.write('Retornos: ' + ', '.join(f'{name}={value}' for name, value in counts.items()))
