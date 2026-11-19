from django.shortcuts import render
from django.views.decorators.http import require_safe
from .manual_content import categories


@require_safe
def manual(request):
    response = render(request, 'usuarios/manual/index.html', {'categories': categories()})
    # Accessible by direct URL while awaiting editorial approval; omit from search indexes.
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
