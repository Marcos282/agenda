from django import template
from django.core.exceptions import ValidationError
from usuarios.models import User
from usuarios.validators import normalizar_whatsapp

register = template.Library()


@register.simple_tag
def contato_rodape(tenant):
    if tenant is None:
        return {}
    owner = User.objects.filter(tenant_id=tenant.pk, tipo=User.Tipo.ADMIN).order_by('pk').first()
    cnpj = getattr(tenant, 'cnpj', '')
    cpf = owner.cpf if owner else ''
    address = getattr(tenant, 'endereco_publico', '')
    if not address and owner:
        address = ', '.join(filter(None, [owner.endereco, owner.numero_endereco, owner.bairro,
            ' - '.join(filter(None, [owner.cidade, owner.estado]))]))
    phone = getattr(tenant, 'telefone', '') or (owner.whatsapp if owner else '')
    whatsapp_url = ''
    if phone:
        try:
            whatsapp_url = 'https://wa.me/' + normalizar_whatsapp(phone).lstrip('+')
        except ValidationError:
            pass
    return {
        'razao_social': getattr(tenant, 'razao_social', '') or tenant.nome,
        'cnpj': cnpj,
        'cpf': f'{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}' if cpf else '',
        'endereco': address,
        'whatsapp_url': whatsapp_url,
    }
