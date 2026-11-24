"""Editorial content only: no tenant queries, remote content or personal data."""
from importlib import import_module
import re
from urllib.parse import urlsplit, parse_qs


# Cole o endereço do vídeo (ou somente o ID). Vazio mostra “Vídeo em breve”.
MANUAL_VIDEOS = {
    'primeiros-passos': 'https://youtu.be/IYXoUnOtWr4',
    'profissionais': 'https://www.youtube.com/watch?v=00OU4AqKa3s',
    'servicos': 'https://www.youtube.com/watch?v=yjPwNG2kYJM',
    'agenda': 'https://www.youtube.com/watch?v=U2MHSaprm8o',
    'clientes': 'https://www.youtube.com/watch?v=-61f04VSTVM',
    'whatsapp': 'https://www.youtube.com/watch?v=p0svx0S9kRU',
    'personalizacao': 'https://www.youtube.com/watch?v=caWfND-vwQk',
    'qr-code': '',
    'renovacao': '',
}

GUIDE_ICONS = {
    'primeira-configuracao': '🚀', 'entrar-no-painel': '🔑',
    'cadastrar-profissional': '👥', 'fotos-profissional': '📷',
    'cadastrar-servico': '✂️', 'vincular-servico': '🔗',
    'consultar-agenda': '📅', 'abrir-agenda': '🕒', 'agenda-em-lote': '🗓️',
    'agendamento-manual': '✍️', 'registrar-atendimento': '✅',
    'consultar-clientes': '🔎', 'reputacao-clientes': '⭐', 'bloquear-cliente': '🔒',
    'conectar-whatsapp': '📱', 'mensagens-whatsapp': '💬', 'respostas-whatsapp': '↩️',
    'personalizar-site': '🎨', 'restaurar-visual': '↺',
    'qr-loja': '▦', 'qr-profissional': '👤',
    'renovar-assinatura': '💳', 'cores-renovacao': '🚦',
}


def guide(slug, title, description, steps, tip, example, related=(), keywords='', icon=None):
    return dict(id=slug, title=title, icon=icon or GUIDE_ICONS.get(slug, '📖'), description=description, steps=steps, tip=tip,
                example=example, related=related, keywords=keywords)


def categories():
    names = ('primeiros_passos', 'profissionais', 'servicos', 'agenda', 'clientes',
             'whatsapp', 'personalizacao', 'qr_code', 'renovacao')
    result = [import_module(f'{__name__}.{name}').CATEGORY for name in names]
    titles = {t['id']: t['title'] for c in result for t in c['tutorials']}
    return [dict(c, video_id=_valid_video_id(MANUAL_VIDEOS.get(c['id'], '')),
                tutorials=[dict(t, links=[dict(id=key, title=titles[key])
                for key in t['related']]) for t in c['tutorials']]) for c in result]


def _valid_video_id(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        return value
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password:
            return ''
        if url.hostname in {'youtu.be', 'www.youtu.be'}:
            candidate = url.path.strip('/')
        elif url.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com',
                              'www.youtube-nocookie.com', 'studio.youtube.com'}:
            parts = url.path.strip('/').split('/')
            if parts[0] == 'watch':
                candidate = parse_qs(url.query).get('v', [''])[0]
            elif len(parts) >= 2 and parts[0] in {'embed', 'shorts', 'live', 'video'}:
                candidate = parts[1]
            else:
                return ''
        else:
            return ''
    except ValueError:
        return ''
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else ''
