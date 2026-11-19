from django.shortcuts import render
from django.views.decorators.http import require_safe
from .manual_content import categories
from .seo import institutional_url, page_metadata, platform_url


@require_safe
def manual(request):
    url = institutional_url('manual')
    title = 'Manual do Tá Combinado | Tutoriais de agendamento online'
    description = (
        'Aprenda a configurar sua agenda online no Tá Combinado. Veja tutoriais sobre '
        'primeiros passos, serviços, profissionais, WhatsApp e compartilhamento da sua loja.'
    )
    data = {
        '@context': 'https://schema.org',
        '@type': 'WebPage',
        'name': title,
        'description': description,
        'url': url,
        'inLanguage': 'pt-BR',
        'isPartOf': {'@id': platform_url() + '#website'},
    }
    return render(request, 'usuarios/manual/index.html', {
        'categories': categories(),
        'institutional_home': platform_url(),
        **page_metadata(title, description, url, data),
    })
