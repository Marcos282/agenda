from functools import wraps
from django.http import Http404


def tenant_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.tenant is None:
            raise Http404("Acesse o subdomínio de um estabelecimento.")
        return view(request, *args, **kwargs)
    return wrapped
