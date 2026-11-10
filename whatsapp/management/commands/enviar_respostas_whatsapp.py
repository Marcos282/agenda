from django.core.management.base import BaseCommand
from whatsapp.replies import process_returns


class Command(BaseCommand):
    help = 'Envia retornos pendentes e repete apenas falhas comprovadamente anteriores ao envio.'

    def handle(self, **options):
        self.stdout.write(f'Retornos aceitos pela API: {process_returns()}')
