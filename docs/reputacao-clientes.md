# Reputação por WhatsApp

A identidade é `(tenant, WhatsApp normalizado)`, usando a função existente `usuarios.validators.normalizar_whatsapp`. Cada reserva preserva seu número em `cliente_whatsapp`; mudanças posteriores no cadastro não transferem seu histórico. Nomes diferentes são reunidos e a lista mostra o nome da reserva mais recente. Números de estabelecimentos diferentes nunca compartilham avaliações.

## Ocorrências e conclusão automática

`ReputacaoCliente` guarda agendamento, tenant, WhatsApp, tipo, pontuação e data de criação. Cada agendamento tem uma única avaliação (`OneToOneField`, unicidade no banco). A restrição `reputacao_tipo_pontos_validos` exige a correspondência entre tipo e pontos; a FK composta `reputacao_ag_tenant_fk` impede ligar avaliações a reservas de outro tenant, inclusive em escritas diretas.

- **Compareceu / CONCLUIDO:** 4 pontos, automaticamente após `fim <= agora` quando o agendamento continua confirmado.
- **Chegou atrasado / ATRASADO:** 3 pontos, ação administrativa após o início de atendimento confirmado.
- **Desmarcou / DESMARCOU:** 2 pontos, pelo fluxo existente de cancelamento antes do início; o horário é liberado.
- **Cliente ausente / AUSENTE:** 1 ponto, pelo fluxo existente de falta após o início.

O término de um atendimento confirmado sem exceção registrada representa comparecimento presumido para a reputação. O administrador deve registrar ausência ou atraso; pode corrigir a avaliação automática posteriormente, alterando a mesma ocorrência em vez de duplicá-la. Não se confirma presença física por WhatsApp.

Para os [lembretes de retorno de 30 dias](lembretes-retorno-30-dias.md), existe uma confirmação explícita e separada: na agenda, após o término, escolha **Confirmar atendimento realizado**. Essa ação registra `Agendamento.conclusao_confirmada_em` e grava/reutiliza a avaliação positiva, preservando um atraso já registrado. A conclusão presumida automática não preenche esse campo e não habilita o lembrete de retorno por si só.

A atualização automática ocorre ao abrir Clientes, seu histórico e a agenda administrativa. Para processar sem acesso ao painel, execute `python manage.py atualizar_reputacoes`; o comando é idempotente e pode ser chamado pelo agendador da implantação. Nenhum cron é instalado automaticamente. Reservas antigas canceladas, com falta ou confirmadas já encerradas também são avaliadas; registros legados sem WhatsApp válido permanecem sem avaliação.

Operações de pontuação usam a trava do profissional e a transação já empregadas nas reservas, cancelamentos e faltas. Reexecuções automáticas preservam avaliações manuais.

## Média e estrelas

A média é calculada a partir das ocorrências, sem campo de média mutável no cadastro. Com zero, uma ou duas avaliações, aparece somente **Cliente Novo**. A partir da terceira:

| Média | Estrelas |
| --- | --- |
| >= 3,5 | ★★★★ |
| >= 2,5 e < 3,5 | ★★★☆ |
| >= 1,5 e < 2,5 | ★★☆☆ |
| < 1,5 | ★☆☆☆ |

Os limites ficam centralizados em `agenda.reputation.LIMITES_ESTRELAS`; a exibição numérica usa uma casa decimal. As estrelas usam a média sem arredondamento prévio. Lista e histórico exibem média e total de avaliações; a agenda exibe a classificação discretamente. Avaliações iniciais são armazenadas e aparecem individualmente no histórico, mesmo enquanto a classificação é Cliente Novo.

## Acesso, instalação e testes

Somente administradores do tenant podem registrar exceções. As ações possuem tela de confirmação e POST com CSRF; GET não pontua manualmente. Os limites diário e de reservas futuras por WhatsApp e o bloqueio de clientes permanecem independentes da reputação.

Aplicar `python manage.py migrate` antes de iniciar esta versão. Não é necessário recriar dados. Executar `python manage.py test agenda.test_reputation painel.test_clientes agenda.test_booking painel.test_agendamento --noinput` em banco de testes isolado. A suíte cobre identidade, isolamento, terceira avaliação, média, pontuação automática/manual, idempotência, unicidade e FK no banco, interface e permissões.

### Validação realizada

Passaram 31 testes da seleção `agenda.test_reputation`, `painel.test_clientes`, `usuarios.test_customer_login_disabled`, `agenda.test_guest_booking` e dos cenários de agenda administrativa, configuração de limites, limite diário e limite futuro em `agenda.test_booking`. O banco `test_barbe` foi criado e removido separadamente do banco da aplicação. As verificações `manage.py check`, `makemigrations --check --dry-run` e de sintaxe do JavaScript passaram.

A suíte antiga completa ainda contém expectativas de login de clientes por senha e datas fixas de abertura que já ficaram no passado; esses casos falham com as regras atuais e precisam de atualização independente. As políticas de autenticação e de abertura de agendas não foram alteradas para satisfazer expectativas antigas.

## Componente visual de estrelas

A lista, o histórico e o resumo da agenda reutilizam `painel/reputacao.html`. Os cartões e o diálogo da agenda utilizam `CustomerReputation.renderRating`, de `painel/static/painel/reputacao.js`. Ambos compartilham as classes e o CSS de `reputacao.css`, carregados na base do painel.

Após três avaliações, sempre há quatro ícones preenchidos `★` do mesmo formato. Estrelas conquistadas usam `#F59E0B` e opacidade 1; estrelas restantes usam `#94A3B8` e opacidade 0,25. O componente informa a nota com `aria-label` e oculta os ícones individuais de leitores de tela. Até duas avaliações, somente o selo Cliente Novo é renderizado.
