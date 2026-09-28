from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from tenants.base import TenantOwnedModel, TenantQuerySet


class Servico(TenantOwnedModel):
    nome = models.CharField(max_length=150)

    class Meta:
        ordering = ['nome', 'pk']
        constraints = [models.UniqueConstraint(fields=['id', 'tenant'], name='servico_id_tenant_unique')]
        indexes = [models.Index(fields=['tenant', 'ativo'], name='servico_tenant_ativo_idx')]

    def __str__(self):
        return self.nome


class ProfissionalServicoQuerySet(TenantQuerySet):
    def disponiveis(self):
        return self.filter(ativo=True, profissional__ativo=True, servico__ativo=True, tenant__ativo=True)


class ProfissionalServico(TenantOwnedModel):
    profissional = models.ForeignKey('profissionais.Profissional', on_delete=models.PROTECT, related_name='servicos')
    servico = models.ForeignKey(Servico, on_delete=models.PROTECT, related_name='profissionais')
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    duracao_minutos = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    tenant_relations = ('profissional', 'servico')
    objects = ProfissionalServicoQuerySet.as_manager()

    class Meta:
        ordering = ['servico__nome', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'profissional', 'servico'], name='prof_servico_tenant_unique'),
            models.UniqueConstraint(fields=['id', 'tenant', 'profissional'], name='ps_id_tenant_prof_unique'),
            models.CheckConstraint(condition=models.Q(valor__gt=0), name='prof_servico_valor_positivo'),
            models.CheckConstraint(condition=models.Q(duracao_minutos__gt=0), name='prof_servico_duracao_positiva'),
        ]
        indexes = [models.Index(fields=['tenant', 'servico', 'ativo'], name='ps_tenant_servico_ativo_idx')]

    def __str__(self):
        return f'{self.profissional} — {self.servico}'
