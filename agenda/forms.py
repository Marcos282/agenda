from django import forms
from django.forms import BaseFormSet, formset_factory


class DiaForm(forms.Form):
    data = forms.DateField(input_formats=['%Y-%m-%d'], widget=forms.DateInput(attrs={'type': 'date'}))


class PeriodoForm(forms.Form):
    hora_inicio = forms.TimeField(label='Início', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time', 'step': '60'}))
    hora_fim = forms.TimeField(label='Fim', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time', 'step': '60'}))

    def clean(self):
        data = super().clean()
        if data.get('hora_inicio') is not None and data.get('hora_fim') is not None:
            if data['hora_inicio'] >= data['hora_fim']:
                self.add_error('hora_fim', 'O fim precisa ser depois do início, no mesmo dia.')
        return data


class BasePeriodosFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        previous_end = None
        for start, end in self.periodos():
            if previous_end is not None and start < previous_end:
                raise forms.ValidationError('Os períodos se sobrepõem. Ajuste os horários antes de salvar.')
            previous_end = end

    def periodos(self):
        return sorted(
            (form.cleaned_data['hora_inicio'], form.cleaned_data['hora_fim'])
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
            and form.cleaned_data.get('hora_inicio') is not None and form.cleaned_data.get('hora_fim') is not None
        )


PeriodosFormSet = formset_factory(
    PeriodoForm, formset=BasePeriodosFormSet, extra=0, can_delete=True,
    max_num=48, validate_max=True, absolute_max=100,
)
