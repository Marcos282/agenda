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
<<<<<<< HEAD
=======

### Campo de boas-vindas

A seção **Boas-vindas e agradecimento** tem formulário próprio, preenchido com a mensagem padrão, botão **Salvar configuração** e as mesmas variáveis dos lembretes. O envio automático é independente da antecedência do lembrete. A migração atualiza apenas mensagens que ainda são exatamente o padrão anterior; textos personalizados são preservados.

## Confirmação automática após novo agendamento

A rota `/painel/whatsapp/` oferece ativação independente, texto editável e prévia que acompanha a digitação. A prévia usa dados fictícios de cliente, serviço e profissional e o nome/fuso do estabelecimento. O administrador pode consultar as últimas confirmações, em páginas de dez registros.

Reutilizamos `whatsapp.Configuracao`: `tenant` é uma relação exclusiva por estabelecimento, `confirmacoes_ativas` controla o envio e `mensagem_confirmacao` guarda o texto. A criação de uma configuração começa com confirmações ativadas e a mensagem padrão de agradecimento. Configurações e textos personalizados existentes são preservados. O formulário exige administrador do tenant da requisição; o histórico também é filtrado por esse tenant.

Variáveis aceitas: `{cliente}`, `{empresa}`, `{profissional}`, `{servico}`, `{data}` e `{horario}`. Os aliases anteriores `{estabelecimento}` e `{hora}` continuam funcionando, inclusive nos lembretes. Formatação adicional e variáveis desconhecidas são rejeitadas. Data e horário usam o fuso do tenant e os nomes registrados no agendamento.

Fluxo: `agenda.booking.reservar` grava a reserva e registra `transaction.on_commit(..., robust=True)` → `whatsapp.services.enviar_confirmacao_agendamento` → `whatsapp.confirmations.send_confirmation` → provedor. Não há disparo no `save()` do model. Cadastros públicos, clientes com conta e agendamentos pelo painel passam por esse mesmo fluxo. Uma transação revertida não envia mensagens. O envio é síncrono após o commit e pode acrescentar a latência da API à resposta da reserva.

`whatsapp.services.renderizar_mensagem_agendamento` centraliza a renderização, também reutilizada pelos lembretes. O envio usa o WhatsApp registrado na reserva; a função existente `usuarios.validators.normalizar_whatsapp` prepara o número internacional sem alterar o cadastro. O adaptador Evolution remove o `+` apenas ao montar a requisição de sua API.

`whatsapp.Confirmacao` mantém um registro exclusivo por agendamento, criado antes da chamada externa para impedir duplicação. A migração `0004` acrescenta `destinatario`, `mensagem` e `resposta_api`; os campos existentes registram início, horário de aceitação, status e erro. O adaptador armazena apenas metadados da resposta (provedor e identificador), sem credenciais ou payload completo. Registros anteriores permanecem com os novos campos vazios. “Aceito pela API” não prova entrega ao telefone.

Falhas esperadas e inesperadas do provedor deixam o registro como “Verificar envio” e geram log com tenant, agendamento e classe do erro. Não cancelam nem apagam a reserva. Não há repetição automática: uma resposta ambígua pode corresponder a uma mensagem já enviada. O callback robusto também protege a reserva se ocorrer erro ao carregar a configuração ou persistir o registro; nesse caso o Django registra a falha do callback.

### Trocar o provedor ou acrescentar mensagens

`whatsapp.providers.get_provider` instancia o adaptador indicado por `WHATSAPP_PROVIDER`, cujo padrão é `whatsapp.providers.EvolutionProvider`. Um adaptador deve implementar `send_text(tenant, number, text)` e retornar um dicionário JSON com metadados seguros da resposta, ou `None`. Ele é responsável por credenciais e instâncias isoladas por tenant. Não devolva segredos nesse dicionário. Configure o caminho Python da nova classe no settings para trocar o transporte das confirmações sem alterar o agendamento. A conexão via QR e o processamento atual dos lembretes ainda usam Evolution.

Para novos eventos (cancelamento, reagendamento etc.), adicione configurações por tenant, um registro idempotente próprio e uma função de serviço que reutilize a renderização e o provedor. Registre o evento com `on_commit` na operação correspondente. Lembretes futuros continuam usando seu processamento periódico; confirmações não dependem de cron.

Aplique as migrações com `myenv/bin/python manage.py migrate` antes de publicar o código. Os testes de confirmação usam provedor simulado, sem envio real.

## Console de testes `/testezap`

Acesse `/testezap` (ou `/testezap/`) no subdomínio do estabelecimento, autenticado como administrador. O botão **Testar envio e recebimento** no painel WhatsApp abre a mesma tela. Ela usa a instância já conectada, sem cadastrar números, criar instâncias ou gerar QR code.

Informe o WhatsApp de destino e o texto, e clique em **Enviar mensagem**. O envio usa o provedor existente e normaliza o destino. A conversa é consultada pela Evolution a cada dez segundos e também pelo botão **Atualizar conversa**, com até 30 mensagens. A página diferencia mensagens enviadas e recebidas e mantém o conteúdo como texto, sem interpretar HTML.

O recebimento consulta `POST /chat/findMessages/{instance}`. O armazenamento de mensagens precisa estar habilitado na Evolution: a instalação descrita em `evolution-local.md` desativa esse histórico, portanto nessa configuração as respostas não aparecerão até habilitá-lo no provedor. Nenhuma configuração do provedor é alterada automaticamente. A consulta filtra a conversa na API e novamente no servidor. Credenciais nunca são enviadas ao navegador; envio e consulta exigem administrador do tenant correto. O console não cria agendamentos nem cadastra clientes.

Referência oficial do endpoint: https://doc.evolution-api.com/v2/api-reference/chat-controller/find-messages . Testes: `myenv/bin/python manage.py test whatsapp.test_console --noinput` (API simulada).
>>>>>>> d4ce4f7 (Primeiro envio: guia pronta)

## Área de diagnóstico `/testes`

Abra `/testes` no subdomínio do estabelecimento, autenticado como administrador, e informe o PIN **1031**. O PIN pode ser alterado pela variável `WHATSAPP_TESTS_PIN` no `.env`. A liberação fica na sessão, vinculada ao tenant, por 30 minutos. Cinco PINs incorretos bloqueiam novas tentativas por dez minutos no cache configurado. O botão **Bloquear área de testes** encerra a liberação; o PIN também protege consultas AJAX e envio.

A área reutiliza o console de envio e conversa, sem cadastro de WhatsApp. **Verificar conexão e configuração** verifica as configurações carregadas, a instância esperada e o estado retornado pela Evolution. Falhas distinguem erros HTTP (incluindo autenticação e instância não encontrada), problemas de conexão e respostas inválidas, sem expor a chave ou o payload externo. O recebimento continua dependendo do histórico habilitado na Evolution. Os testes usam API simulada.

### Teste completo de ida e volta

Em `/testes`, preencha o destino e a mensagem e clique em **Testar envio e recebimento**. Será enviada uma mensagem real com um código aleatório `TESTE-…`. Responda pelo celular de destino com esse código. A consulta periódica confirma o teste apenas quando encontra uma mensagem recebida (não enviada pela loja) da conversa correta com o código desta tentativa. Mensagens antigas sem esse código e a própria mensagem de saída não confirmam o recebimento.

A sessão guarda a última tentativa, tenant, destino, código, identificador devolvido pela API, horário e resultado. Os estados são falha no envio, mensagem aceita/aguardando resposta e ida e volta confirmada. Uma mensagem aceita pela API ainda não prova entrega. Sem histórico da Evolution, a resposta não pode ser verificada pela tela. Verificar a conexão ou abrir a página não dispara mensagens; o envio exige o botão e o PIN liberado.
