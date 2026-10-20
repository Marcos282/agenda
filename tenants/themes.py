"""Presentation-only catalog; no operational models or writes belong here."""
import re

THEMES = [
    ('minimalista', 'Minimalista', 'Simples e elegante', '#287454', '#fafbf9', '#ffffff', '#24312b', '8px', 'none', 'sans-serif'),
    ('moderno', 'Moderno', 'Contemporâneo', '#6366f1', '#f4f6fb', '#ffffff', '#172033', '20px', '0 12px 35px #16233b15', 'sans-serif'),
    ('glassmorphism', 'Glassmorphism', 'Transparências e vidro', '#7c3aed', '#ede9fe', '#ffffffb8', '#281b42', '24px', '0 12px 35px #5b21b625', 'sans-serif'),
    ('neumorphism', 'Neumorphism', 'Sombras e relevos suaves', '#427a88', '#e8eef0', '#e8eef0', '#263c43', '24px', '8px 8px 18px #bec8cc, -8px -8px 18px #ffffff', 'sans-serif'),
    ('dark-premium', 'Dark Premium', 'Escuro e sofisticado', '#d4af37', '#111318', '#1e222b', '#f2f3f5', '16px', '0 14px 35px #00000055', 'sans-serif'),
    ('corporativo', 'Corporativo', 'Empresarial', '#1e40af', '#f1f5f9', '#ffffff', '#172a43', '5px', '0 3px 10px #172a4310', 'sans-serif'),
    ('futurista', 'Futurista', 'Tecnológico', '#00d4ff', '#091421', '#102335', '#e5f8ff', '4px', '0 0 24px #00d4ff25', 'monospace'),
    ('material', 'Material Design', 'Moderno e funcional', '#6750a4', '#f7f2fa', '#fffbfe', '#25202c', '18px', '0 3px 8px #25202c25', 'sans-serif'),
    ('brutalista', 'Brutalista', 'Contrastes marcantes', '#facc15', '#fffdf4', '#ffffff', '#151515', '0px', '6px 6px 0 #151515', 'monospace'),
    ('classico', 'Clássico', 'Tradicional e elegante', '#755537', '#f8f3e9', '#fffdf8', '#352b24', '3px', '0 4px 14px #352b2410', 'Georgia, serif'),
    ('gradiente', 'Gradiente', 'Transições de cores', '#b13edc', '#fcf3ff', '#ffffff', '#39184b', '24px', '0 10px 30px #b13edc20', 'sans-serif'),
    ('retro', 'Retrô', 'Vintage', '#b34b32', '#f3e7cb', '#fff4d9', '#463826', '12px', '4px 4px 0 #8d714b', 'Georgia, serif'),
    ('podologia', 'Podologia', 'Delicado e acolhedor', '#66bfbf', '#f5f0e8', '#ffffff', '#29494a', '28px', '0 5px 18px #29494a10', 'sans-serif'),
    ('odontologia', 'Odontologia', 'Clínico e profissional', '#2196f3', '#f0fbfc', '#ffffff', '#183c50', '12px', '0 5px 18px #2196f315', 'sans-serif'),
    ('personal-trainer', 'Personal Trainer', 'Esportivo e energético', '#ff6b00', '#151515', '#232323', '#f8f8f8', '4px', '0 5px 18px #00000035', 'sans-serif'),
]
THEME_CHOICES = [('original', 'Aparência original')] + [(t[0], t[1]) for t in THEMES]
PALETTE = ['#2196f3', '#287454', '#7c3aed', '#ff6b00', '#dc2626', '#151515', '#facc15', '#66bfbf']
ICONS = [('', 'Original'), ('✂', 'Barbearia'), ('✧', 'Salão de beleza'), ('♡', 'Podologia'), ('🦷', 'Odontologia'), ('⚡', 'Personal Trainer'), ('✦', 'Estética'), ('↗', 'Fisioterapia'), ('☀', 'Psicologia'), ('🐾', 'Pet Shop'), ('❀', 'Massoterapia')]
SUGGESTIONS = {
    'Barbearia': 'Seu estilo começa aqui', 'Salão de beleza': 'Sua beleza merece atenção especial',
    'Podologia': 'Seus pés merecem cuidado especial', 'Odontologia': 'Seu sorriso é nossa prioridade',
    'Personal Trainer': 'Transforme seus objetivos em resultados', 'Estética': 'Realce sua beleza natural',
    'Fisioterapia': 'Movimento e qualidade de vida', 'Psicologia': 'Um espaço de acolhimento',
    'Pet Shop': 'Cuidado e carinho para seu melhor amigo', 'Massoterapia': 'Seu momento de relaxamento',
}


def luminance(color):
    rgb = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
    return sum(w * (c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4) for w, c in zip((.2126, .7152, .0722), rgb))


def contrast_color(color):
    return '#000000' if luminance(color) > .179 else '#ffffff'


def readable_accent(color, background):
    """Keep the hue when possible, then shade toward an accessible text color."""
    target = contrast_color(background)
    base = luminance(background)
    for step in range(21):
        ratio = step / 20
        mixed = '#' + ''.join(f'{round(int(color[i:i+2], 16)*(1-ratio)+int(target[i:i+2], 16)*ratio):02x}' for i in (1, 3, 5))
        value = luminance(mixed)
        if (max(value, base)+.05)/(min(value, base)+.05) >= 4.5:
            return mixed
    return target


def tokens(style, color):
    theme = next((t for t in THEMES if t[0] == style), THEMES[0])
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        color = theme[3]
    return {'primary': color, 'accent_ink': readable_accent(color, theme[4]), 'on_primary': contrast_color(color), 'background': theme[4],
            'surface': theme[5], 'text': theme[6], 'radius': theme[7], 'shadow': theme[8], 'font': theme[9]}


def gallery():
    return [dict(id=t[0], name=t[1], description=t[2], color=t[3], tokens=tokens(t[0], t[3])) for t in THEMES]
