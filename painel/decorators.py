from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from tenants.decorators import tenant_required
from usuarios.models import User


def admin_tenant_required(view):
    @tenant_required
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if (not request.user.is_active or request.user.tipo != User.Tipo.ADMIN
                or request.user.tenant_id != request.tenant.pk):
            raise PermissionDenied('Apenas administradores deste estabelecimento podem acessar o painel.')
        return view(request, *args, **kwargs)
    return wrapped
