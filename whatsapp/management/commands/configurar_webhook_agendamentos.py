from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from tenants.models import Tenant
from whatsapp import evolution
from whatsapp.reply_views import webhook_token


class Command(BaseCommand):
    help = 'Consulta ou configura o webhook autenticado de respostas aos lembretes.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', required=True)
        parser.add_argument('--aplicar', action='store_true', help='Grava a configuração na Evolution API.')

    def handle(self, **options):
        tenant = Tenant.objects.filter(subdomain=options['tenant'], ativo=True).first()
        if not tenant:
            raise CommandError('Estabelecimento ativo não encontrado.')
        name = evolution.instance(tenant)
        host = f'{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}'
        target = f'https://{host}/whatsapp/respostas/'
        try:
            current = evolution.request('GET', '/webhook/find/' + name) or {}
            if not isinstance(current, dict):
                raise CommandError('Resposta inesperada do webhook.')
            previous = current.get('url', '')
            if previous:
                parts = urlsplit(previous)
                if parts.scheme != 'https' or parts.netloc != host or parts.path.rstrip('/') not in {
                        '/whatsapp/respostas', '/teste/receber', '/testes/whatsapp/receber'} or parts.query:
                    raise CommandError('Webhook de outra integração encontrado. Não foi alterado; configure encaminhamento autenticado dos eventos.')
                # Known inbox endpoints also process reminder replies. Keep them.
                target = previous
            events = current.get('events') or []
            headers = current.get('headers') or {}
            if not isinstance(events, list) or not isinstance(headers, dict):
                raise CommandError('Configuração atual inválida.')
            if not options['aplicar']:
                self.stdout.write('Consulta concluída. Para configurar, repita com --aplicar. Nenhum segredo foi exibido.')
                return
            headers = {**headers, 'X-Agendamento-Token': webhook_token(tenant)}
            if urlsplit(target).path.rstrip('/') != '/whatsapp/respostas':
                from whatsapp.inbox_views import webhook_token as inbox_token
                headers['X-TestZap-Token'] = inbox_token(tenant)
            evolution.request('POST', '/webhook/set/' + name, {'webhook': {
                'enabled': True, 'url': target, 'headers': headers, 'byEvents': False,
                'base64': False, 'events': list(dict.fromkeys(events + ['MESSAGES_UPSERT'])),
            }})
            updated = evolution.request('GET', '/webhook/find/' + name)
            if not isinstance(updated, dict) or not (
                updated.get('enabled') and updated.get('url') == target
                and 'MESSAGES_UPSERT' in (updated.get('events') or [])
                and (updated.get('headers') or {}).get('X-Agendamento-Token') == webhook_token(tenant)
                and not updated.get('webhookByEvents', updated.get('byEvents', False))
            ):
                raise CommandError('A Evolution não confirmou toda a configuração. Confira a versão e os cabeçalhos suportados.')
        except evolution.EvolutionError as exc:
            # EvolutionError already contains a sanitized, actionable diagnostic.
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS('Webhook configurado. Nenhuma mensagem foi enviada.'))
