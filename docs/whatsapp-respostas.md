# Confirmação de presença e cancelamento pelo WhatsApp

Implementação local; nenhum deploy ou alteração de webhook é feito automaticamente.
As opções começam **desativadas** para todos os estabelecimentos.

## Estrutura e regras

- `whatsapp/reminders.py` mantém o registro exclusivo de envio por agendamento.
  Se pelo menos uma opção de resposta estiver ativa, renderiza o novo lembrete
  com as opções habilitadas, usando o renderizador de variáveis existente.
  Com ambas desativadas, preserva a mensagem personalizada anterior.
- `Lembrete` guarda instância, destinatário normalizado, ID devolvido pela API,
  data de envio, validade até o início da reserva, permissões oferecidas no
  envio e datas de confirmação de presença/cancelamento pelo cliente.
- `RespostaLembrete` registra identificador do evento, tenant, instância,
  remetente, horário do provedor, horário de recebimento, opção e resultado.
  Não guarda o texto livre nem o payload recebido. A restrição única por
  tenant/instância/mensagem e o bloqueio transacional do tenant evitam repetição,
  inclusive com mensagens distintas e processamento simultâneo.
- `RetornoResposta` é a caixa de saída persistente, exclusiva por evento.
  O evento e a alteração de agenda são confirmados antes de enviar o retorno.
  Não se desfaz um cancelamento porque a API ficou indisponível.
- `replies.py` identifica um lembrete por tenant, instância, remetente do
  envelope autenticado, período de validade e ID citado quando presente.
  Uma citação incorreta não permite procurar outra reserva pelo telefone.
  Sem citação, só age se houver exatamente um lembrete identificável na janela.
  Se houver ambiguidade, orienta o cliente a usar **Responder** no lembrete.
- Eventos sem horário verificável, anteriores ao envio, posteriores à validade,
  próprios, de grupos ou de outros tipos não alteram a reserva. Mudanças no
  horário ou destinatário da reserva invalidam o lembrete anterior.
- `1` registra presença confirmada; não conclui atendimento nem cria avaliação.
  O registro é preservado caso posteriormente o administrador marque falta.
- `2` usa `agenda.booking.cancelar`, que libera o horário e reaproveita
  `ReputacaoCliente` com `DESMARCOU`. Não cria outra estrutura de reputação.
  Cancelamentos seguem a política atual de não ocupar a linha do tempo.
- A agenda exibe indicador separado do status operacional; o histórico do
  cliente exibe confirmação, cancelamento e tentativas ligadas à reserva.
  Nenhuma resposta, por si só, gera penalização.

## Migração e ativação

A migração necessária é `whatsapp/0006_respostas_lembretes.py`.
Faça backup e siga o processo habitual de deploy antes de executar, no ambiente
alvo, com o virtualenv e banco corretos:

```bash
python manage.py migrate --plan
python manage.py migrate
python manage.py check
python manage.py collectstatic --noinput
```

Esses comandos **não são executados automaticamente em produção**.

No painel do estabelecimento, abra **WhatsApp**:

1. Mantenha a conexão Evolution ativa e os lembretes habilitados.
2. Em **Confirmação por WhatsApp**, ative confirmação e/ou cancelamento.
3. Defina a antecedência mínima de cancelamento e salve.

Não havia campo de prazo mínimo de cancelamento na implementação inspecionada:
o cancelamento existente só proíbe atendimento já iniciado. Foi acrescentado
`Configuracao.cancelamento_antecedencia_minutos`, de 0 a 10080 minutos,
exclusivo para WhatsApp, com padrão 0 para preservar essa regra. Ele é distinto
da antecedência de **envio** do lembrete. Não altera cancelamentos administrativos
ou pelo link público. As opções de confirmação e cancelamento são independentes
do envio de boas-vindas (`confirmacoes_ativas`).

Lembretes antigos não ganham permissões retroativamente. Ativar uma opção
depois do envio não permite usá-la se o lembrete não a oferecia; desativá-la
impede novas alterações imediatamente.

## Webhook Evolution

Endpoint por estabelecimento:

`https://ESTABELECIMENTO.tacombinado.net/whatsapp/respostas/`

O Django exige o cabeçalho `X-Agendamento-Token`, derivado da chave Django e do
tenant. O comando configura esse cabeçalho sem imprimir seu valor. Não use a
chave global da Evolution no navegador ou em parâmetros de URL.

Após publicar e migrar, consulte primeiro:

```bash
python manage.py configurar_webhook_agendamentos --tenant marcos
```

Para gravar efetivamente a configuração remota:

```bash
python manage.py configurar_webhook_agendamentos --tenant marcos --aplicar
```

Repita para cada instância/estabelecimento que optar pelo recurso. O comando
reutiliza `evolution.instance(tenant)`, mantém os eventos e cabeçalhos existentes,
adiciona `MESSAGES_UPSERT` e desativa o sufixo por evento (`byEvents=false`).
Recusa sobrescrever webhooks de integrações desconhecidas. Os endpoints de
caixa de testes conhecidos (`/teste/receber/` e `/testes/whatsapp/receber`) foram
adaptados para também processar respostas; se já estiverem configurados, o
comando preserva a URL e mantém os dois cabeçalhos necessários. Não é necessário
interromper a caixa de testes. Não execute comandos antigos para sobrescrever
o novo endpoint.

Formato aceito: Evolution v2, `event: messages.upsert` ou `MESSAGES_UPSERT`,
`instance`, `data` como objeto ou lista, `key.id`, `key.fromMe=false`,
`key.remoteJid` com `@s.whatsapp.net`, `messageTimestamp` em segundos Unix e
texto em `message.conversation` ou `message.extendedTextMessage.text`.
Citações usam `contextInfo.stanzaId`. JIDs `@lid` exigem `remoteJidAlt` fornecido
pela própria API com o número real. Não se extrai telefone do texto da mensagem.

Referência: [webhooks oficiais da Evolution](https://github.com/evolution-foundation/evolution-docs/blob/main/docs/02-Configuration/Webhooks.md).
Não foi possível consultar a versão instalada no ambiente acessível. Antes de
ativar em produção, confirme suporte a cabeçalhos customizados e o formato real
do evento com um número de teste autorizado. Sem autenticação, sem ID ou sem
timestamp verificável, não há alteração automática. Não foi enviado WhatsApp
real nem alterada uma configuração remota durante a implementação.

Se trocar `DJANGO_SECRET_KEY`, reconfigure os cabeçalhos dos webhooks. Use chaves,
prefixos de instância e bancos distintos entre desenvolvimento e produção.

## Retornos e indisponibilidade

O retorno é tentado após o commit. Para recuperar retornos pendentes e falhas
comprovadamente anteriores ao envio, execute a cada minuto, no mesmo ambiente
do Django:

```bash
python manage.py enviar_respostas_whatsapp
```

Mantenha também o processamento já existente `enviar_lembretes`. Use o cron ou
timer habitual do servidor; não foi instalado agendamento automático.

São permitidas até cinco tentativas com espera progressiva. Somente rejeições
inequívocas anteriores ao envio, como autenticação/configuração ou HTTP
400/401/403/404/429, são repetidas. Timeout, resposta inválida, desconexão ou
erro 5xx deixam **INCERTO**. Queda do processo após a reivindicação pode deixar
**PROCESSANDO**. Esses casos não são reenviados automaticamente: conferir a
conversa/metadados antes de qualquer intervenção. A Evolution não oferece aqui
uma garantia comprovada de envio exatamente uma vez; repetir cegamente pode
duplicar mensagens. O painel mostra os últimos 20 retornos e seus estados.

As auditorias e mensagens da caixa de saída contêm dados pessoais necessários
à operação; mantenha acesso administrativo, backup e política de retenção
apropriados. Não há logging do telefone, texto livre, token ou payload completo.

## Validação local

Use PostgreSQL **descartável**, sem credenciais de produção, e desative
integrações externas. Não execute a suíte contra um banco compartilhado.

```bash
python manage.py test whatsapp.test_replies whatsapp.test_replies_browser
python manage.py test whatsapp.tests whatsapp.test_confirmations whatsapp.test_returns whatsapp.test_webhook_setup whatsapp.test_console
python manage.py test painel.test_agenda_reputacao painel.test_clientes painel.test_agendamento agenda.test_reputation agenda.test_booking
python manage.py check
python manage.py makemigrations --check --dry-run
```

Os testes usam API simulada, PostgreSQL real com transações/bloqueios e Chrome
para agenda/histórico. Não substituem a validação ponta a ponta da versão da
Evolution e de um aparelho real antes da ativação em produção.

### Resultados desta implementação

- 117 testes do WhatsApp e navegador: aprovados.
- 18 testes adicionais de envio e concorrência: aprovados, incluindo resposta
  recebida enquanto o lembrete ainda está sendo enviado.
- 35 testes novos no total (34 de backend/concorrência e um de navegador).
- `manage.py check`: sem problemas. `makemigrations --check --dry-run`: sem
  mudanças pendentes. A migração foi aplicada pelos bancos descartáveis de teste.
- Regressão ampliada de agenda/reputação: 51 de 59 testes aprovados. Os outros
  oito casos (sete falhas e um erro) foram reproduzidos **com os mesmos nomes**
  em uma cópia intacta de `HEAD`, antes destas alterações: sessões de clientes
  desativadas, histórico e limite de reservas. Não foram alterados fora do escopo.
- A suíte JavaScript via Node não pôde ser executada porque Node não está
  instalado; o teste de navegador executou o JavaScript real da agenda no Chrome.

## Arquivos da entrega

- Modelos e migração: `whatsapp/models.py`, `whatsapp/migrations/0006_respostas_lembretes.py`.
- Recebimento e transações: `whatsapp/replies.py`, `whatsapp/reply_views.py`,
  `whatsapp/inbox_views.py`, `barbe/urls.py`.
- Envio: `whatsapp/reminders.py`, `whatsapp/evolution.py`.
- Comandos: `whatsapp/management/commands/configurar_webhook_agendamentos.py`,
  `whatsapp/management/commands/enviar_respostas_whatsapp.py`.
- Configurações: `whatsapp/views.py`, `whatsapp/templates/whatsapp/configuracao.html`.
- Agenda: `agenda/presentation.py`, `painel/static/painel/agenda.js`,
  `painel/templates/painel/agenda/dia.html`, `painel/templates/painel/agenda/resumo.html`.
- Histórico: `painel/cliente_views.py`, `painel/templates/painel/cliente_historico.html`.
- Testes: `whatsapp/test_replies.py`, `whatsapp/test_replies_browser.py`.
- Documentação: `README.md`, `docs/whatsapp-respostas.md`.
