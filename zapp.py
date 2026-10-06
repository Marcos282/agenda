"""Teste pelo mesmo provider usado em /teste/, no ambiente do servidor."""
import argparse
import os
import sys


DEFAULT_MESSAGE = (
    'Olá! 😊 Já faz cerca de 30 dias desde o seu último corte de cabelo. '
    'Que tal renovar o visual? Estamos esperando por você! ✂️'
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant', default='marcos', help='Subdomínio do estabelecimento (padrão: marcos).')
    parser.add_argument('--numero', default='21990921092', help='WhatsApp de destino com DDD.')
    parser.add_argument('--mensagem', default=DEFAULT_MESSAGE)
    parser.add_argument('--enviar', action='store_true', help='Enviar uma mensagem; sem esta opção, apenas verificar a conexão.')
    args = parser.parse_args(argv)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barbe.settings')
    import django
    django.setup()
    from django.core.exceptions import ValidationError
    from django.db import DatabaseError
    from tenants.models import Tenant
    from usuarios.validators import normalizar_whatsapp
    from whatsapp.evolution import EvolutionError, configured, connection_info
    from whatsapp.providers import get_provider

    try:
        numero = normalizar_whatsapp(args.numero)
        if not args.mensagem.strip() or len(args.mensagem) > 2000:
            raise ValidationError('Informe uma mensagem de 1 a 2.000 caracteres.')
        tenant = Tenant.objects.get(subdomain=args.tenant, ativo=True)
        if not configured():
            raise EvolutionError('Configure a integração Evolution no ambiente da aplicação.')
        info = connection_info(tenant)
        if info['state'] != 'open':
            raise EvolutionError(f'WhatsApp do estabelecimento não conectado (estado: {info["state"]}).')
        print(f'Estabelecimento: {tenant.nome} ({tenant.subdomain})')
        print(f'WhatsApp conectado: {info["number"] or "número não informado"}')
        print(f'Destino: {numero}')
        if not args.enviar:
            print('Conexão verificada. Use --enviar para enviar uma única mensagem.')
            return 0
        result = get_provider().send_text(tenant, numero, args.mensagem)
        if not isinstance(result, dict) or not result.get('message_id'):
            raise EvolutionError('Envio sem confirmação. Confira a conversa antes de repetir.')
        print(f'Mensagem aceita pela API. ID: {result["message_id"]}. Confira o recebimento no celular.')
        return 0
    except Tenant.DoesNotExist:
        print(f'Estabelecimento ativo "{args.tenant}" não encontrado neste banco. '
              'Execute no servidor que hospeda /teste/, com o ambiente virtual da aplicação.', file=sys.stderr)
    except DatabaseError:
        print('Não foi possível acessar o banco. Use o mesmo ambiente da aplicação no servidor.', file=sys.stderr)
    except (ValidationError, EvolutionError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(f'Falha no teste ({type(exc).__name__}). Confira a conversa antes de repetir o envio.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
