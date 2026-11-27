from django import forms
from django.utils.translation import gettext_lazy as _


class LogoBriefForm(forms.Form):
    STYLES = [
        ('modern', _('Moderno')),
        ('minimalist', _('Minimalista')),
        ('elegant', _('Elegante')),
        ('classic', _('Clássico')),
        ('luxurious', _('Luxuoso')),
        ('creative', _('Criativo')),
        ('professional', _('Profissional')),
    ]

    name = forms.CharField(label=_('Nome do estabelecimento'), max_length=150)
    segment = forms.CharField(label=_('Segmento de atuação'), max_length=120)
    primary_color = forms.RegexField(r'^#[a-fA-F0-9]{6}$', label=_('Cor principal'),
                                    widget=forms.TextInput(attrs={'type': 'color'}))
    secondary_color = forms.RegexField(r'^#[a-fA-F0-9]{6}$', label=_('Cor secundária'),
                                      widget=forms.TextInput(attrs={'type': 'color'}))
    style = forms.ChoiceField(label=_('Estilo da logomarca'), choices=STYLES)
    description = forms.CharField(label=_('Descrição adicional (opcional)'), required=False,
                                  max_length=600, widget=forms.Textarea(attrs={'rows': 3}))
    request_id = forms.UUIDField(widget=forms.HiddenInput())
