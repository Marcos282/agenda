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
            unchanged = self.pk and type(self).objects.filter(
                pk=self.pk, tenant_id=self.tenant_id, profissional_id=self.profissional_id,
                data=self.data, hora_inicio=self.hora_inicio, hora_fim=self.hora_fim, ativo=True,
            ).exists()
            if not unchanged:
                from .validation import validar_inicio_abertura
                validar_inicio_abertura(tenant=self.tenant, data=self.data)
            overlaps = type(self).objects.filter(
                tenant_id=self.tenant_id, profissional_id=self.profissional_id,
                data=self.data, ativo=True, hora_inicio__lt=self.hora_fim, hora_fim__gt=self.hora_inicio,
            ).exclude(pk=self.pk)
            if overlaps.exists():
                raise ValidationError('Já existe um período ativo sobreposto para este profissional nesta data.')


    def save(self, *args, **kwargs):
        from django.db import transaction
        from profissionais.models import Profissional
        from .booking import validar_cobertura
        with transaction.atomic():
            # Also protect the legacy period editor, which does not use configurar_dia.
            old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            unchanged = old and old.ativo and all((
                old.tenant_id == self.tenant_id,
                old.profissional_id == self.profissional_id,
                old.data == self.data,
                old.hora_inicio == self.hora_inicio,
                old.hora_fim == self.hora_fim,
            ))
            if self.ativo and not unchanged:
                from .validation import validar_inicio_abertura
                validar_inicio_abertura(tenant=self.tenant, data=self.data)
            ids = sorted({self.profissional_id} | ({old.profissional_id} if old else set()))
            list(Profissional.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
            if old:
                dates = {(old.profissional_id, old.data), (self.profissional_id, self.data)}
                for prof_id, day in dates:
                    periods = list(type(self).objects.filter(tenant_id=self.tenant_id,
                        profissional_id=prof_id, data=day, ativo=True).exclude(pk=self.pk).values_list('hora_inicio', 'hora_fim'))
                    if self.ativo and self.profissional_id == prof_id and self.data == day:
                        periods.append((self.hora_inicio, self.hora_fim))
                    validar_cobertura(tenant=self.tenant, profissional_id=prof_id, data=day, periodos=periods)
            return super().save(*args, **kwargs)


class Agendamento(models.Model):
    class Status(models.TextChoices):
        CONFIRMADO = 'CONFIRMADO', 'Confirmado'
        CANCELADO = 'CANCELADO', 'Cancelado'
        NAO_COMPARECEU = 'NAO_COMPARECEU', 'Não compareceu'

    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    cliente = models.ForeignKey('usuarios.User', on_delete=models.PROTECT, related_name='agendamentos', null=True, blank=True)
    contato = models.ForeignKey('usuarios.ContatoCliente', on_delete=models.PROTECT, related_name='agendamentos', null=True, blank=True)
    oferta = models.ForeignKey('catalogo.ProfissionalServico', on_delete=models.PROTECT, related_name='agendamentos')
    profissional = models.ForeignKey('profissionais.Profissional', on_delete=models.PROTECT, related_name='agendamentos')
    acesso_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    cliente_nome = models.CharField(max_length=150)
    cliente_whatsapp = models.CharField(max_length=16, blank=True, default='')
    servico_nome = models.CharField(max_length=150)
    profissional_nome = models.CharField(max_length=150)
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    duracao_minutos = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMADO)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    cancelado_em = models.DateTimeField(null=True, blank=True)
    nao_compareceu_em = models.DateTimeField(null=True, blank=True)
    conclusao_confirmada_em = models.DateTimeField(null=True, blank=True)
    objects = TenantQuerySet.as_manager()

    class Meta:
        ordering = ['inicio', 'pk']
        indexes = [models.Index(fields=['tenant', 'cliente', 'inicio'], name='ag_cliente_inicio_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(cliente__isnull=False, contato__isnull=True) | models.Q(cliente__isnull=True, contato__isnull=False), name='ag_cliente_ou_contato'),
            models.CheckConstraint(condition=models.Q(inicio__lt=models.F('fim')), name='ag_inicio_antes_fim'),
            models.CheckConstraint(condition=models.Q(valor__gt=0, duracao_minutos__gt=0), name='ag_valor_duracao_positivos'),
            models.CheckConstraint(condition=models.Q(status='CONFIRMADO', cancelado_em__isnull=True, nao_compareceu_em__isnull=True) | models.Q(status='CANCELADO', cancelado_em__isnull=False, nao_compareceu_em__isnull=True) | models.Q(status='NAO_COMPARECEU', cancelado_em__isnull=True, nao_compareceu_em__isnull=False), name='ag_status_consistente'),
            models.UniqueConstraint(fields=['id', 'tenant'], name='ag_id_tenant_unique'),
            ExclusionConstraint(name='ag_sem_sobreposicao', expressions=[
                ('tenant', RangeOperators.EQUAL), ('profissional', RangeOperators.EQUAL),
                (models.Func('inicio', 'fim', models.Value('[)'), function='TSTZRANGE', output_field=DateTimeRangeField()), RangeOperators.OVERLAPS),
            ], condition=models.Q(status__in=['CONFIRMADO', 'NAO_COMPARECEU']), violation_error_message='Esse horário já está reservado.'),
        ]

    def clean(self):
        super().clean()
        if self.cliente_id and self.cliente.tenant_id != self.tenant_id:
            raise ValidationError('Cliente de outro estabelecimento.')
        if self.contato_id and self.contato.tenant_id != self.tenant_id:
            raise ValidationError('Contato de outro estabelecimento.')
        if self.oferta_id and (self.oferta.tenant_id != self.tenant_id or self.oferta.profissional_id != self.profissional_id):
            raise ValidationError('Serviço e profissional devem pertencer ao estabelecimento.')
        if self.inicio and self.fim and self.duracao_minutos:
            from datetime import timedelta
            if self.fim - self.inicio != timedelta(minutes=self.duracao_minutos):
                raise ValidationError('A duração deve corresponder ao intervalo reservado.')

    @property
    def whatsapp_contato(self):
        return self.contato.whatsapp if self.contato_id else self.cliente.whatsapp

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ReputacaoCliente(models.Model):
    class Tipo(models.TextChoices):
        CONCLUIDO = 'CONCLUIDO', 'Compareceu'
        ATRASADO = 'ATRASADO', 'Chegou atrasado'
        DESMARCOU = 'DESMARCOU', 'Desmarcou'
        AUSENTE = 'AUSENTE', 'Cliente ausente'

    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    whatsapp_normalizado = models.CharField(max_length=16)
    agendamento = models.OneToOneField(Agendamento, on_delete=models.PROTECT, related_name='avaliacao_reputacao')
    pontuacao = models.PositiveSmallIntegerField()
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = TenantQuerySet.as_manager()

    class Meta:
        indexes = [models.Index(fields=['tenant', 'whatsapp_normalizado'], name='reputacao_tenant_whatsapp_idx')]
        constraints = [models.CheckConstraint(condition=(
            models.Q(tipo='CONCLUIDO', pontuacao=4) | models.Q(tipo='ATRASADO', pontuacao=3) |
            models.Q(tipo='DESMARCOU', pontuacao=2) | models.Q(tipo='AUSENTE', pontuacao=1)
        ), name='reputacao_tipo_pontos_validos')]

    def clean(self):
        super().clean()
        from usuarios.validators import normalizar_whatsapp
        self.whatsapp_normalizado = normalizar_whatsapp(self.whatsapp_normalizado)
        if self.agendamento_id:
            booking = Agendamento.objects.for_tenant(self.tenant).filter(pk=self.agendamento_id).first()
            if booking is None:
                raise ValidationError('Avaliação e agendamento devem pertencer ao mesmo estabelecimento.')
            if self.whatsapp_normalizado != normalizar_whatsapp(booking.cliente_whatsapp or booking.whatsapp_contato):
                raise ValidationError('A avaliação deve usar o WhatsApp do agendamento.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
