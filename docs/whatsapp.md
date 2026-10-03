# WhatsApp e lembretes

No painel, **WhatsApp** fica ao lado de **+ Agendamento**. Cada tenant tem sua configuração e instância Evolution própria. Apenas administradores do tenant podem acessar, editar e conectar.

A mensagem admite `{cliente}`, `{servico}`, `{profissional}`, `{estabelecimento}`, `{data}` e `{hora}`. O fuso é o do tenant. A antecedência padrão é 120 minutos, ajustável de 1 a 10080 minutos. Lembretes começam desativados; salve a opção de ativação após preparar a conexão.

## Preparar o servidor

Configure no ambiente do Django **e do processo de lembretes**:

```dotenv
EVOLUTION_API_URL=https://sua-evolution.example.com
EVOLUTION_API_KEY=sua-chave
EVOLUTION_INSTANCE_PREFIX=barbe_tenant
```

Use HTTPS em produção. A chave fica no servidor e nunca aparece no painel. O prefixo deve ser exclusivo deste banco/ambiente, com letras, números, hífen ou underscore. Não altere depois de conectar instâncias. Não reutilize prefixos de outra aplicação.

```bash
myenv/bin/python manage.py migrate
```

Abra `/painel/whatsapp/`, gere o QR code, escaneie em Aparelhos conectados e clique em **Verificar conexão**. Salve a mensagem, a antecedência e ative os lembretes.

## Processamento automático

O Gunicorn sozinho não executa tarefas periódicas. Execute a cada minuto, com o mesmo ambiente e banco do Django:

```bash
/home/marcos/barbe/myenv/bin/python /home/marcos/barbe/manage.py enviar_lembretes
```

Exemplo de cron (o usuário do cron precisa receber as variáveis acima e as variáveis DB_* / DJANGO_SECRET_KEY da aplicação; adapte os caminhos no servidor):

```cron
* * * * * cd /home/marcos/barbe && /usr/bin/flock -n /tmp/barbe-whatsapp.lock /home/marcos/barbe/myenv/bin/python manage.py enviar_lembretes >> /home/marcos/barbe/lembretes.log 2>&1
```

Configure rotação do log. Este cron é um exemplo e **não é instalado automaticamente**. O comando envia mensagens reais para configurações ativas; não use como teste com dados reais sem intenção de envio.

## Regras de envio

- Um lembrete por agendamento confirmado, ainda futuro, dentro da antecedência configurada. Verificação a cada minuto implica precisão de aproximadamente um minuto, além da latência da API.
- Inclui clientes com conta e contatos cadastrados no painel, usando o WhatsApp atual cadastrado.
- Agendamentos criados dentro da antecedência entram na próxima execução. Após indisponibilidade, pendentes futuros dentro da janela também entram; nunca envia lembretes de horários já iniciados.
- Cancelamentos e faltas são excluídos. A reserva é bloqueada durante a chamada de envio para serializar alterações concorrentes; uma mensagem já enviada não pode ser retirada se o cancelamento acontecer depois.
- Antecedência/mensagem novas valem para envios pendentes. Não repete lembretes já processados.
- API desconectada ou indisponível na consulta inicial deixa os lembretes pendentes para a próxima execução.
- Cada envio é registrado antes da chamada externa. Timeout, falha de envio ou interrupção deixam o registro incerto/iniciado, sem repetição automática para evitar duplicidade. O administrador deve conferir a conversa. Não há garantia de entrega nem retentativa automática de envios incertos.
- O painel exibe os dez últimos registros; “Aceito pela API” não significa entregue/lido.

Implementação Evolution v2: `fetchInstances`, `instance/create`, `instance/connect`, `instance/logout`, `message/sendText`, com integração `WHATSAPP-BAILEYS`. Referência do provedor: https://github.com/EvolutionAPI/evolution-api/blob/main/src/api/routes/sendMessage.router.ts . Validação local usa mocks, sem conectar números nem enviar mensagens reais.

## Instalação local deste projeto

A instalação sem Docker e os serviços desta máquina estão descritos em [evolution-local.md](evolution-local.md). A configuração local protegida pode fornecer a URL e a chave quando as variáveis de ambiente não estiverem definidas; variáveis de ambiente têm prioridade.

### Campo de boas-vindas

A seção **Boas-vindas e agradecimento** tem formulário próprio, preenchido com a mensagem padrão, botão **Salvar mensagem de boas-vindas** e as mesmas variáveis dos lembretes. O envio automático é independente da antecedência do lembrete. A migração atualiza apenas mensagens que ainda são exatamente o padrão anterior; textos personalizados são preservados.
