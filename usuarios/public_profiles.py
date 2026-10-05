"""Public store details shared by profiles and QR codes."""
from .models import User


def endereco_fisico(tenant):
    admin = User.objects.filter(tenant=tenant, tipo='ADMIN', is_active=True).order_by('pk').first()
    if not admin:
        return ''
    street = ', '.join(filter(None, [admin.endereco, admin.numero_endereco]))
    city = ' / '.join(filter(None, [admin.cidade, admin.estado]))
    return ' — '.join(filter(None, [street, admin.bairro, city]))

