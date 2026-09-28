from django import forms
from usuarios.forms import WhatsAppField


class DataAgendamentoForm(forms.Form):
    data = forms.DateField(label='Escolha a data', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))


class ConfirmarAgendamentoForm(forms.Form):
    whatsapp = WhatsAppField()
    nome = forms.CharField(label='Seu nome', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'name'}))
    hora = forms.TimeField(label='Horário', input_formats=['%H:%M'], widget=forms.HiddenInput)
    cotacao = forms.CharField(widget=forms.HiddenInput)
