from string import Formatter
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

DEFAULT_MESSAGE = 'Olá, {cliente}! Lembramos do seu agendamento de {servico} com {profissional} em {estabelecimento}, dia {data} às {hora}. Esperamos você!'
INTERACTIVE_MESSAGE = 'Olá, {cliente}! 👋\n\nLembramos do seu agendamento de {servico} com {profissional} em {estabelecimento}, dia {data} às {hora}.\n\nPor favor, confirme sua presença:\n\n{opcoes}\n\nEsperamos você!'
DEFAULT_CONFIRMATION = 'Olá, {cliente}! 😊\n\nAgradecemos pela preferência!\n\nSeu horário está reservado para {data} às {horario}, com {profissional}.\n\nServiço: {servico}\n\nAguardamos você no horário combinado.\n\n{empresa}'
VARIABLES = {'cliente', 'servico', 'profissional', 'empresa', 'horario', 'estabelecimento', 'data', 'hora'}
DEFAULT_RETURN_MESSAGE = 'Olá, {nome}! 😊 Já se passaram cerca de 30 dias desde o seu último atendimento. Que tal renovar o visual? Estamos esperando por você! ✂️'
RETURN_VARIABLES = {'nome', 'estabelecimento', 'profissional', 'ultimo_atendimento'}


def validate_message(value):
    validate_template(value, VARIABLES)


def validate_return_message(value):
    validate_template(value, RETURN_VARIABLES)


def validate_template(value, variables):
    try:
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None and (name not in variables or spec or conversion):
                raise ValueError
    except ValueError:
        raise ValidationError('Use apenas as variáveis indicadas, entre chaves, sem formatação adicional.')


class Configuracao(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE)
    lembretes_ativos = models.BooleanField(default=False, verbose_name='Ativar lembretes automáticos')
    antecedencia_minutos = models.PositiveIntegerField(default=120, validators=[MinValueValidator(1), MaxValueValidator(10080)], verbose_name='Antecedência em minutos')
    mensagem_lembrete = models.TextField(default=DEFAULT_MESSAGE, max_length=2000, validators=[validate_message], verbose_name='Mensagem do lembrete')
    retornos_ativos = models.BooleanField(default=False, verbose_name='Enviar lembrete de retorno após 30 dias')
    mensagem_retorno = models.TextField(default=DEFAULT_RETURN_MESSAGE, max_length=2000,
        validators=[validate_return_message], verbose_name='Mensagem de retorno')
    confirmacoes_ativas = models.BooleanField(default=True, verbose_name='Enviar confirmação após o agendamento')
    mensagem_confirmacao = models.TextField(default=DEFAULT_CONFIRMATION, max_length=2000, validators=[validate_message], verbose_name='Mensagem de confirmação e agradecimento')
    atualizado_em = models.DateTimeField(auto_now=True)
    confirmar_presenca_whatsapp = models.BooleanField(default=False, verbose_name='Ativar confirmação automática de presença')
    cancelar_whatsapp = models.BooleanField(default=False, verbose_name='Permitir cancelamento por WhatsApp')
    cancelamento_antecedencia_minutos = models.PositiveIntegerField(default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10080)],
        verbose_name='Antecedência mínima para cancelamento em minutos',
        help_text='0 permite cancelar até o início. Aplica-se ao cancelamento por WhatsApp.')

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(antecedencia_minutos__gte=1, antecedencia_minutos__lte=10080), name='whatsapp_antecedencia_valida'),
            models.CheckConstraint(condition=models.Q(cancelamento_antecedencia_minutos__lte=10080), name='wa_prazo_cancelamento_valido')]


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
    instancia = models.CharField(max_length=200, blank=True)
    destinatario = models.CharField(max_length=16, blank=True)
    mensagem_id = models.CharField(max_length=200, blank=True)
    valido_ate = models.DateTimeField(null=True, blank=True)
    permite_confirmar = models.BooleanField(default=False)
    permite_cancelar = models.BooleanField(default=False)
    presenca_confirmada_em = models.DateTimeField(null=True, blank=True)
    cancelado_pelo_cliente_em = models.DateTimeField(null=True, blank=True)


class RespostaLembrete(models.Model):
    """Minimal audit of authenticated inbound events; no raw provider payload."""
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    instancia = models.CharField(max_length=200)
    mensagem_id = models.CharField(max_length=200)
    destinatario = models.CharField(max_length=16)
    lembrete = models.ForeignKey(Lembrete, null=True, blank=True, on_delete=models.PROTECT, related_name='respostas')
    opcao = models.CharField(max_length=5)
    resultado = models.CharField(max_length=40, default='RECEBIDO')
    ocorrido_em = models.DateTimeField()
    recebido_em = models.DateTimeField(auto_now_add=True)

    def get_resultado_display(self):
        return {
            'CONFIRMADO': 'Presença confirmada', 'CANCELADO': 'Cancelado pelo cliente',
            'FORA_DO_PRAZO': 'Tentativa de cancelamento fora do prazo',
            'JA_CONFIRMADO': 'Confirmação já registrada', 'INATIVO': 'Agendamento já encerrado ou cancelado',
            'EXPIRADO': 'Resposta fora da validade', 'AMBIGUO': 'Solicitada identificação do agendamento',
            'SEM_LEMBRETE': 'Nenhum lembrete correspondente', 'DESATIVADO': 'Opção desativada',
            'DATA_INVALIDA': 'Horário da mensagem inválido', 'ORIENTADO': 'Opções informadas ao cliente',
            'RECEBIDO': 'Resposta recebida',
        }.get(self.resultado, 'Resposta registrada')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant', 'instancia', 'mensagem_id'], name='wa_resposta_evento_unico')]


class RetornoResposta(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Aguardando envio'
        PROCESSANDO = 'PROCESSANDO', 'Envio iniciado'
        ENVIADO = 'ENVIADO', 'Aceito pela API'
        FALHA = 'FALHA', 'Falha segura para nova tentativa'
        INCERTO = 'INCERTO', 'Verificar envio antes de repetir'
    resposta = models.OneToOneField(RespostaLembrete, on_delete=models.PROTECT, related_name='retorno')
    mensagem = models.TextField()
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDENTE)
    tentativas = models.PositiveIntegerField(default=0)
    proxima_tentativa_em = models.DateTimeField(default=timezone.now)
    enviado_em = models.DateTimeField(null=True, blank=True)
    mensagem_id = models.CharField(max_length=200, blank=True)
    erro = models.CharField(max_length=100, blank=True)


class Confirmacao(models.Model):
    destinatario = models.CharField(max_length=16, blank=True)
    mensagem = models.TextField(blank=True)
    resposta_api = models.JSONField(default=dict, blank=True)
    agendamento = models.OneToOneField('agenda.Agendamento', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Lembrete.Status, default=Lembrete.Status.PROCESSANDO)
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    erro = models.CharField(max_length=250, blank=True)


class LembreteRetorno(models.Model):
    """One delivery claim per completed appointment; tenant/customer come from it."""
    class Status(models.TextChoices):
        PROCESSANDO = 'PROCESSANDO', 'Envio iniciado'
        ENVIADO = 'ENVIADO', 'Aceito pela API'
        ERRO = 'ERRO', 'Falha antes do envio'
        INCERTO = 'INCERTO', 'Verificar envio'
        IGNORADO = 'IGNORADO', 'Não elegível no momento do envio'

    agendamento = models.OneToOneField('agenda.Agendamento', on_delete=models.PROTECT,
        related_name='lembrete_retorno')
    destinatario = models.CharField(max_length=16, blank=True)
    mensagem = models.TextField(blank=True)
    resposta_api = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSANDO)
    criado_em = models.DateTimeField(auto_now_add=True)
    tentado_em = models.DateTimeField(null=True, blank=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    erro = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(models.Q(status='ENVIADO', enviado_em__isnull=False)
                | models.Q(status__in=['PROCESSANDO', 'ERRO', 'INCERTO', 'IGNORADO'], enviado_em__isnull=True)),
            name='retorno_status_envio_consistente')]
