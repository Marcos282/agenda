import getpass
import json
import os
import tempfile
from email.utils import parseaddr
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = 'Salva a configuração Resend no arquivo local protegido, solicitando a chave sem exibi-la.'

    def handle(self, **options):
        sender = input('Remetente verificado no Resend (ex.: Tá Combinado <nao-responda@tacombinado.net>): ').strip()
        try:
            validate_email(parseaddr(sender)[1])
        except ValidationError:
            raise CommandError('Informe um remetente válido.') from None
        if '\n' in sender or '\r' in sender:
            raise CommandError('Remetente inválido.')
        key = getpass.getpass('Chave de API do Resend (não será exibida): ').strip()
        if not key.startswith('re_') or any(c.isspace() for c in key):
            raise CommandError('A chave deve começar com re_ e não conter espaços.')
        path = settings.BASE_DIR / '.local-settings.json'
        config = json.loads(path.read_text()) if path.exists() else {}
        config.update(RESEND_API_KEY=key, RESEND_FROM_EMAIL=sender)
        fd, tmp = tempfile.mkstemp(prefix='.resend-', dir=settings.BASE_DIR)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(config, f, indent=2)
                f.write('\n')
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self.stdout.write(self.style.SUCCESS('Resend salvo no arquivo local protegido. Reinicie o Django/Gunicorn para aplicar. Nenhum e-mail foi enviado.'))
        if 'RESEND_API_KEY' in os.environ or 'RESEND_FROM_EMAIL' in os.environ:
            self.stdout.write('Atenção: as variáveis de ambiente RESEND_* existentes têm prioridade sobre este arquivo.')
