"""Configure the test inbox using server-side Evolution credentials."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from tenants.models import Tenant
from whatsapp import evolution
from whatsapp.inbox_views import webhook_token


def verify_endpoint(url, tenant):
    payload = {'instance': evolution.instance(tenant), 'event': 'test.endpoint', 'data': {}}
    request = Request(url, data=json.dumps(payload).encode(), headers={
        'Content-Type': 'application/json', 'X-TestZap-Token': webhook_token(tenant),
    }, method='POST')
    try:
        with build_opener(evolution.NoRedirect).open(request, timeout=10) as response:
            result = json.load(response)
        if result != {'ignored': True}:
            raise ValueError
    except Exception:
        raise CommandError('O endpoint não respondeu corretamente. Publique /teste/receber/ e confira HTTPS e a chave Django antes de configurar.') from None


class Command(BaseCommand):
    help = 'Configura o webhook Evolution de recebimento SQLite para um estabelecimento.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', required=True, help='Subdomínio do estabelecimento, por exemplo marcos.')

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(subdomain=options['tenant'], ativo=True)
        except Tenant.DoesNotExist:
            raise CommandError('Estabelecimento ativo não encontrado.') from None
        url = f'https://{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}/teste/receber/'
        name = evolution.instance(tenant)
        try:
            current = evolution.request('GET', '/webhook/find/' + name)
            if current is not None and not isinstance(current, dict):
                raise CommandError('Resposta inesperada ao consultar o webhook atual.')
            current = current or {}
            previous = current.get('url', '')
            if previous:
                parts = urlsplit(previous)
                target = urlsplit(url)
                if parts.netloc != target.netloc or parts.path.rstrip('/') not in {
                    '/teste/receber', '/testes/whatsapp/receber',
                }:
                    raise CommandError('Já existe webhook de outra integração. Não foi alterado; é necessário encaminhar os eventos também para a caixa de testes.')
            verify_endpoint(url, tenant)
            events = current.get('events') or []
            if not isinstance(events, list):
                raise CommandError('Lista de eventos atual inválida.')
            headers = current.get('headers') or {}
            if not isinstance(headers, dict):
                raise CommandError('Cabeçalhos atuais inválidos.')
            headers = {**headers, 'X-TestZap-Token': webhook_token(tenant)}
            evolution.request('POST', '/webhook/set/' + name, {'webhook': {
                'enabled': True, 'url': url, 'headers': headers,
                'byEvents': False, 'base64': False,
                'events': list(dict.fromkeys(events + ['MESSAGES_UPSERT'])),
            }})
            updated = evolution.request('GET', '/webhook/find/' + name)
            if not isinstance(updated, dict) or not (updated.get('enabled') and updated.get('url') == url
                    and 'MESSAGES_UPSERT' in (updated.get('events') or [])
                    and (updated.get('headers') or {}).get('X-TestZap-Token') == webhook_token(tenant)):
                raise CommandError('A API não confirmou toda a configuração. Consulte os registros do provedor.')
        except evolution.EvolutionError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(f'Webhook configurado para {tenant.nome}: {url}'))
        self.stdout.write('Responda pelo celular e consulte /teste/. Nenhuma mensagem de WhatsApp foi enviada por este comando.')
