# Lembretes de retorno após 30 dias — Tá Combinado

## Configuração por estabelecimento

Em `/painel/whatsapp/`, antes do lembrete de agendamento, a seção **Lembrete de retorno** contém:

- **Enviar lembrete de retorno após 30 dias**, desativado por padrão.
- **Mensagem de retorno**, editável e independente das mensagens já existentes.
- Botão **Salvar lembrete de retorno**.

Quando desativado, nenhum envio de retorno é iniciado para esse tenant. Abrir ou salvar a página nunca dispara mensagens: o comando diário executa a seleção e o envio.

Mensagem padrão:

> Olá, {nome}! 😊 Já se passaram cerca de 30 dias desde o seu último atendimento. Que tal renovar o visual? Estamos esperando por você! ✂️

| Variável | Valor |
| --- | --- |
| `{nome}` | Nome preservado no atendimento; se vazio, `cliente`. |
| `{estabelecimento}` | Nome do tenant; se vazio, `nosso estabelecimento`. |
| `{profissional}` | Nome preservado do profissional; se vazio, `nossa equipe`. |
| `{ultimo_atendimento}` | Data de término do atendimento, em `dd/mm/aaaa`, no fuso do tenant. |

Outras variáveis, atributos, conversões e especificadores de formatação são rejeitados. Use `{{` e `}}` para chaves literais. Limite de 2.000 caracteres.

## Atendimento efetivamente realizado

A análise dos modelos mostrou que o projeto não tinha confirmação explícita de conclusão: a reputação presume comparecimento após terminar uma reserva confirmada, quando não há falta/cancelamento.

Para não disparar retorno apenas porque o horário passou, esta funcionalidade acrescenta `Agendamento.conclusao_confirmada_em`. Após o término, o administrador abre o atendimento na agenda e escolhe **Confirmar atendimento realizado**. A operação é idempotente, registra a confirmação e reutiliza a avaliação `ReputacaoCliente`: **CONCLUIDO / Compareceu**, preservando **ATRASADO / Chegou atrasado** quando já registrado.

A reputação automática existente não preenche esse campo. Não há preenchimento retroativo automático: confirme os atendimentos históricos apenas quando realmente realizados. A confirmação não envia WhatsApp imediatamente; somente habilita a origem para o processamento diário.

São elegíveis apenas atendimentos com confirmação explícita, resultado positivo registrado, agendamento ainda confirmado e término já encerrado. Falta, cancelamento, reserva sem confirmação de realização e atendimento futuro/em andamento não são considerados. A data de cadastro do cliente não participa do cálculo.

O ciclo usa a data de término do atendimento no fuso do tenant, não a data em que o administrador clicou para confirmar. Assim, confirmar hoje um atendimento realizado há 30 dias não acrescenta outros 30 dias de espera.

## Seleção e ciclos

1. Localizar tenants ativos com retorno habilitado.
2. Obter o último atendimento realizado por `(tenant, WhatsApp normalizado)`, ordenado pelo término e, em empate, pelo ID.
3. Só depois comparar a data local de término com a data local atual menos 30 dias.
4. Excluir clientes inativos e números bloqueados no estabelecimento.
5. Verificar a reserva de envio e revalidar configuração, cliente e último atendimento antes do provider.

Nomes diferentes, contas `User` e contatos `ContatoCliente` com o mesmo WhatsApp compartilham o ciclo somente dentro do tenant. Mudanças posteriores no cadastro não alteram o número preservado na reserva. A identidade da avaliação é conferida contra o WhatsApp do atendimento antes de enviar.

| Evento | Data |
| --- | --- |
| Atendimento realizado | 06/10/2026 |
| Primeiro lembrete elegível | 05/11/2026 |
| Novo atendimento realizado | 12/11/2026 |
| Novo lembrete elegível | 12/12/2026 |

Um atendimento realizado recentemente impede usar o atendimento antigo, mesmo que ele ainda não tivesse recebido lembrete. Clientes com mais de 30 dias podem receber no primeiro processamento após ativação. Reservas futuras, ainda não realizadas, não reiniciam o ciclo.

O processo diário consulta diretamente o banco; não depende de abrir `/painel/whatsapp/` ou outra página para encontrar clientes. A confirmação da realização é uma ação operacional da agenda, não uma condição de visita à tela de WhatsApp.

## Integração, auditoria e duplicidade

O envio reutiliza `whatsapp.providers.get_provider().send_text`, atualmente ligado à Evolution. Não há outro transporte nem tabelas paralelas de clientes/atendimentos.

`LembreteRetorno` guarda somente auditoria e controle de envio. Sua relação única com `Agendamento` impede dois controles para o mesmo atendimento. Tenant e cliente são obtidos desse atendimento protegido por `PROTECT`; não existe outro campo tenant que possa divergir da origem.

Campos auditáveis: atendimento, destinatário, texto, criação, tentativa, confirmação de envio, status, erro e ID da mensagem retornado pelo provider. Cliente, conta/contato e tenant são acessíveis pela relação `agendamento`. O histórico paginado em `/painel/whatsapp/` é restrito ao tenant autenticado.

| Status | Significado | Reexecução automática |
| --- | --- | --- |
| `PROCESSANDO` | Reserva persistida antes da rede; pode indicar interrupção. | Não; conferir manualmente. |
| `ENVIADO` | Provider retornou `message_id`; `enviado_em` preenchido. | Não, mesmo em dias posteriores. |
| `ERRO` | Falha de validação antes de iniciar envio. | Sim, depois de corrigir a causa, usando o mesmo registro. |
| `INCERTO` | Erro/resposta sem confirmação após iniciar a chamada. | Não; conferir a conversa. |
| `IGNORADO` | Deixou de ser elegível entre seleção e envio. | Só se voltar a ser elegível; nenhum envio foi iniciado. |

Somente após confirmação do provider o registro é marcado como enviado. Aceitação pela API não comprova entrega/leitura. Erros não preenchem `enviado_em`; logs e auditoria não incluem credenciais ou respostas completas da API.

Uma reserva persistida antes da rede, unicidade por atendimento e travas transacionais no PostgreSQL protegem execuções repetidas/simultâneas. Sem idempotência na API externa não é possível garantir entrega exatamente uma vez após timeout: a política conservadora deixa o resultado incerto para conferência, evitando repetição automática.

Antes de recuperar manualmente `PROCESSANDO`/`INCERTO`, confira a conversa e os logs do provider. Não apague auditorias de mensagens aceitas para forçar reenvio.

## Publicação

Após atualizar o código no servidor:

```bash
cd /var/www/html/combinado
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart combinado
```

Abra `/painel/whatsapp/`, conecte o número do estabelecimento, revise a mensagem e ative o checkbox. Configurações antigas permanecem desativadas. As migrations não enviam mensagens.

## Comando diário

```bash
cd /var/www/html/combinado
venv/bin/python manage.py enviar_lembretes_30_dias
```

Usa o banco/ambiente da aplicação e informa contagens de `enviados`, `erros`, `incertos` e `ignorados`. O `.env` do projeto é carregado pelas configurações Django. Use o usuário e as variáveis do serviço; não coloque segredos na linha de comando/crontab.

O comando envia mensagens reais se a funcionalidade estiver ativada. Uma falha individual não interrompe os demais clientes; consulte contagens, logs e histórico. Nenhuma alteração feita nesta implementação instala agendadores ou ativa envios automaticamente.

## Cron

Na crontab do usuário da aplicação, às 09:00 no fuso do cron do servidor:

```cron
0 9 * * * cd /var/www/html/combinado && venv/bin/python manage.py enviar_lembretes_30_dias >> /var/www/html/combinado/retornos-30-dias.log 2>&1
```

Garanta permissão no arquivo de log e configure sua rotação. O horário da execução depende do cron, mas a elegibilidade sempre respeita o fuso de cada tenant. Não é necessário rodar `atualizar_reputacoes` antes desse comando: a confirmação explícita já grava o resultado necessário.

## Alternativa: systemd timer do usuário

Escolha cron **ou** systemd para esta rotina. Crie `~/.config/systemd/user/combinado-retornos.service`:

```ini
[Unit]
Description=Tá Combinado — lembretes de retorno após 30 dias

[Service]
Type=oneshot
WorkingDirectory=/var/www/html/combinado
# Se necessário: EnvironmentFile=/caminho/do/arquivo-de-ambiente-do-servico
ExecStart=/var/www/html/combinado/venv/bin/python manage.py enviar_lembretes_30_dias
```

Crie `~/.config/systemd/user/combinado-retornos.timer`:

```ini
[Unit]
Description=Verificação diária de retornos do Tá Combinado

[Timer]
OnCalendar=*-*-* 09:00:00 America/Araguaina
Persistent=true
RandomizedDelaySec=5m
Unit=combinado-retornos.service

[Install]
WantedBy=timers.target
```

Como o usuário da aplicação:

```bash
systemctl --user daemon-reload
systemctl --user enable --now combinado-retornos.timer
systemctl --user list-timers combinado-retornos.timer
journalctl --user -u combinado-retornos.service -n 50 --no-pager
```

Para funcionar sem sessão SSH, o usuário deve ter linger habilitado; a implantação documentada já habilita para `marcos`. Em outra instalação: `sudo loginctl enable-linger marcos`.

## Validação

```bash
TENANT_BASE_DOMAIN=localhost DJANGO_DEBUG=true myenv/bin/python manage.py test whatsapp.test_returns whatsapp.test_confirmations whatsapp.tests agenda.test_reputation painel.test_agenda_ajax --noinput
myenv/bin/python manage.py check
myenv/bin/python manage.py makemigrations --check --dry-run
```

Testes com PostgreSQL e envio simulado cobrem 30 dias, último atendimento, novos ciclos, confirmação de realização, falta/cancelamento, isolamento, configuração, variáveis, falhas, auditoria, unicidade e dois workers simultâneos.

## Arquivos modificados/criados

- `agenda/models.py`: campo de confirmação explícita da realização.
- `agenda/migrations/0011_agendamento_conclusao_confirmada_em.py`: migration do campo, sem preencher histórico.
- `agenda/reputation.py`: confirmação idempotente, reutilizando os resultados existentes.
- `agenda/presentation.py`: ação de conclusão no payload da agenda.
- `painel/agendamento_views.py`, `painel/urls.py`: view e rota de confirmação por tenant.
- `painel/templates/painel/agendamento_concluir.html`: confirmação do atendimento realizado.
- `painel/templates/painel/agenda/resumo.html`: ação de conclusão também no resumo HTML da agenda.
- `painel/static/painel/agenda.js`: acesso à ação na agenda.
- `whatsapp/models.py`: configuração, validação de mensagem e auditoria.
- `whatsapp/migrations/0005_configuracao_mensagem_retorno_and_more.py`: configuração e auditoria.
- `whatsapp/views.py`: formulário, salvamento e histórico por tenant.
- `whatsapp/templates/whatsapp/configuracao.html`: checkbox, mensagem e auditoria.
- `whatsapp/returns.py`: seleção, revalidação, envio e controle de duplicidade.
- `whatsapp/management/commands/enviar_lembretes_30_dias.py`: execução diária.
- `whatsapp/test_returns.py`: testes automatizados.
- `docs/lembretes-retorno-30-dias.md`: esta documentação.
- `docs/reputacao-clientes.md`, `README.md`: documentação e links atualizados.
