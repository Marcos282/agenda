from time import sleep

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from tenants.logo_generation import claim_job, process_job


class Command(BaseCommand):
    help = 'Processa a fila de logomarcas fora do servidor web.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Processa no máximo uma solicitação e encerra.')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            job_id = claim_job()
            if job_id:
                process_job(job_id)
            if options['once']:
                return
            if not job_id:
                sleep(2)
