# Reputação por WhatsApp

A identidade é `(tenant, contato preparado)`, usando `usuarios.validators.preparar_whatsapp`: números válidos são normalizados, enquanto outros contatos informados são preservados. Cada reserva mantém o contato usado no atendimento; alterações posteriores no cadastro não transferem o histórico. Contatos iguais em estabelecimentos diferentes nunca compartilham avaliações.

## Avaliações

`ReputacaoCliente` preserva tenant, WhatsApp, agendamento, tipo, pontuação, data do atendimento, data de registro e responsável pelo lançamento. A restrição `OneToOneField` impede avaliações duplicadas para o mesmo agendamento, e a FK composta `reputacao_ag_tenant_fk` impede associar uma avaliação a um agendamento de outro tenant.

- **Compareceu pontualmente / CONCLUIDO:** 4 pontos.
- **Compareceu atrasado / ATRASADO:** 3 pontos.
- **Não compareceu / AUSENTE:** 0 ponto.
- **Cancelou dentro do prazo / DESMARCOU:** ocorrência mantida no histórico, mas não conta como avaliação nem reduz a nota.

Agendamentos futuros, em andamento ou ainda sem avaliação não entram no cálculo. Agendamentos confirmados recebem avaliação automática de comparecimento após o término; administradores podem corrigir uma avaliação automática ou registrar atraso/falta. As correções preservam o registro atual, criam uma linha de auditoria com valores anteriores e novos, data e usuário responsável, e não criam avaliações duplicadas.

Para os [lembretes de retorno de 30 dias](lembretes-retorno-30-dias.md), a confirmação explícita de atendimento continua separada da reputação. Ela não é requisito para o cálculo e a conclusão presumida automática não habilita o lembrete por si só.

A atualização automática ocorre ao abrir Clientes, o histórico ou a agenda administrativa. Para processar sem acesso ao painel, execute `python manage.py atualizar_reputacoes`; o comando é idempotente e pode ser chamado por um agendador. Reservas antigas canceladas, com falta ou confirmadas já encerradas são processadas; registros sem contato permanecem sem avaliação. Nenhuma migração ou alteração de banco de produção é executada automaticamente durante o desenvolvimento.

## Cálculo e exibição

A nota é calculada com `Decimal` diretamente dos eventos originais:

`R = (0,70 × M5) + (0,30 × MH)`

`M5` é a média dos cinco atendimentos avaliados mais recentes; quando há menos de cinco, usa todos os disponíveis. `MH` é a média histórica de todas as avaliações válidas. O ordenamento usa a data do atendimento e, em caso de empate, o identificador do agendamento. Não há média armazenada nem reutilização de nota arredondada. O arredondamento para duas casas ocorre somente na apresentação.

Até duas avaliações válidas, o painel mostra **Cliente Novo — Reputação em formação**, sem atribuir nota ou estrelas. A partir da terceira, a ficha administrativa exibe quatro estrelas laranjas, preenchimento proporcional (incluindo frações), nota no formato `3,77/4`, quantidade e contagens de comparecimentos pontuais, atrasos e faltas. A fórmula e a exclusão dos cancelamentos são explicadas na ficha.

A lista, o histórico e a agenda reutilizam `painel/reputacao.html` ou `CustomerReputation.renderRating`, de `painel/static/painel/reputacao.js`. A exibição permanece restrita ao painel administrativo do tenant e não é publicada para clientes. A reputação não bloqueia agendamentos automaticamente.

## Acesso, correções e testes

Somente administradores autenticados do estabelecimento podem registrar exceções e corrigir avaliações. As ações usam POST com CSRF; a ficha do cliente permite selecionar a avaliação correta e mostra as alterações auditadas em ordem temporal. Os limites de agendamentos e bloqueios por WhatsApp permanecem independentes da reputação.

Aplicar `python manage.py migrate` em implantação após backup e validação em banco de testes isolado. A migração preenche a data do atendimento a partir do agendamento e ajusta a pontuação histórica de faltas para zero, preservando a pontuação anterior no registro de auditoria. Executar `python manage.py test agenda.test_reputation painel.test_agenda_reputacao painel.test_clientes whatsapp.test_returns --noinput`.
