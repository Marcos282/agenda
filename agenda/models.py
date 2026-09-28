from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from tenants.base import TenantOwnedModel, TenantQuerySet


def janela_range():
    # Date + time produces a LOCAL timestamp (without time zone) in PostgreSQL.
    # This is an opening window in the tenant's wall clock, not a booked instant.
    return models.Func(
        models.ExpressionWrapper(models.F('data') + models.F('hora_inicio'), output_field=models.DateTimeField()),
        models.ExpressionWrapper(models.F('data') + models.F('hora_fim'), output_field=models.DateTimeField()),
        models.Value('[)'), function='TSRANGE', output_field=DateTimeRangeField(),
    )


class DisponibilidadeQuerySet(TenantQuerySet):
    def disponiveis(self):
        return self.filter(ativo=True, profissional__ativo=True, tenant__ativo=True)


class Disponibilidade(TenantOwnedModel):
    profissional = models.ForeignKey('profissionais.Profissional', on_delete=models.PROTECT, related_name='disponibilidades')
    data = models.DateField()
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    tenant_relations = ('profissional',)
    objects = DisponibilidadeQuerySet.as_manager()

    class Meta:
        ordering = ['data', 'hora_inicio', 'pk']
        indexes = [models.Index(fields=['tenant', 'profissional', 'data'], name='disp_tenant_prof_data_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(hora_inicio__lt=models.F('hora_fim')), name='disp_inicio_antes_fim'),
            ExclusionConstraint(
                name='disp_sem_sobreposicao',
                expressions=[('tenant', RangeOperators.EQUAL), ('profissional', RangeOperators.EQUAL), (janela_range(), RangeOperators.OVERLAPS)],
                condition=models.Q(ativo=True),
                violation_error_message='Já existe um período ativo sobreposto para este profissional nesta data.',
            ),
        ]

    def clean(self):
        super().clean()
        if self.hora_inicio is not None and self.hora_fim is not None:
            if self.hora_inicio >= self.hora_fim:
                raise ValidationError({'hora_fim': 'O fim deve ser posterior ao início, no mesmo dia.'})
        if self.ativo and all([self.tenant_id, self.profissional_id, self.data, self.hora_inicio, self.hora_fim]):
            overlaps = type(self).objects.filter(
                tenant_id=self.tenant_id, profissional_id=self.profissional_id,
                data=self.data, ativo=True, hora_inicio__lt=self.hora_fim, hora_fim__gt=self.hora_inicio,
            ).exclude(pk=self.pk)
            if overlaps.exists():
                raise ValidationError('Já existe um período ativo sobreposto para este profissional nesta data.')
