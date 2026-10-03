from string import Formatter
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

DEFAULT_MESSAGE = 'Olá, {cliente}! Lembramos do seu agendamento de {servico} com {profissional} em {estabelecimento}, dia {data} às {hora}. Esperamos você!'
DEFAULT_CONFIRMATION = 'Olá, {cliente}! 😊\n\nAgradecemos pela preferência!\n\nSeu horário está reservado para {data} às {horario}, com {profissional}.\n\nServiço: {servico}\n\nAguardamos você no horário combinado.\n\n{empresa}'
VARIABLES = {'cliente', 'servico', 'profissional', 'empresa', 'horario', 'estabelecimento', 'data', 'hora'}


def validate_message(value):
    try:
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None and (name not in VARIABLES or spec or conversion):
                raise ValueError
    except ValueError:
        raise ValidationError('Use apenas as variáveis indicadas, entre chaves, sem formatação adicional.')


class Configuracao(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE)
    lembretes_ativos = models.BooleanField(default=False, verbose_name='Ativar lembretes automáticos')
    antecedencia_minutos = models.PositiveIntegerField(default=120, validators=[MinValueValidator(1), MaxValueValidator(10080)], verbose_name='Antecedência em minutos')
    mensagem_lembrete = models.TextField(default=DEFAULT_MESSAGE, max_length=2000, validators=[validate_message], verbose_name='Mensagem do lembrete')
    confirmacoes_ativas = models.BooleanField(default=True, verbose_name='Enviar confirmação após o agendamento')
    mensagem_confirmacao = models.TextField(default=DEFAULT_CONFIRMATION, max_length=2000, validators=[validate_message], verbose_name='Mensagem de confirmação e agradecimento')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(antecedencia_minutos__gte=1, antecedencia_minutos__lte=10080), name='whatsapp_antecedencia_valida')]


class Lembrete(models.Model):
    class Status(models.TextChoices):
        PROCESSANDO = 'PROCESSANDO', 'Envio iniciado'
        ENVIADO = 'ENVIADO', 'Aceito pela API'
        INCERTO = 'INCERTO', 'Verificar envio'
    agendamento = models.OneToOneField('agenda.Agendamento', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status, default=Status.PROCESSANDO)
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    erro = models.CharField(max_length=250, blank=True)


class Confirmacao(models.Model):
    destinatario = models.CharField(max_length=16, blank=True)
    mensagem = models.TextField(blank=True)
    resposta_api = models.JSONField(default=dict, blank=True)
    agendamento = models.OneToOneField('agenda.Agendamento', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Lembrete.Status, default=Lembrete.Status.PROCESSANDO)
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    erro = models.CharField(max_length=250, blank=True)
