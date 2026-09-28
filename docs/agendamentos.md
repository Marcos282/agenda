# Agendamentos do cliente

O cliente escolhe uma oferta (serviço + profissional), consulta a data, entra ou cria uma conta e confirma um horário. A confirmação é automática. Não há pagamento online, notificações externas ou aprovação manual nesta etapa.

## Rotas

- `/agendamentos/servico/<oferta_id>/`: escolha da data.
- `/agendamentos/servico/<oferta_id>/<AAAA-MM-DD>/`: horários e confirmação via POST com CSRF.
- `/agendamentos/`: histórico do usuário conectado, com paginação.
- `/agendamentos/<id>/`: comprovante e cancelamento via POST pelo próprio cliente, antes do início.

As rotas exigem o subdomínio do estabelecimento. O login e o cadastro preservam o destino selecionado, rejeitando redirecionamentos externos. O cadastro ainda é seguido de login.

## Intervalos e integridade

`Agendamento` armazena instantes UTC de início/fim, cliente, oferta, profissional, estado e cópias dos nomes, preço e duração no momento da reserva. Alterações posteriores no catálogo não mudam esses dados históricos.

Os horários sugeridos são calculados a partir dos intervalos livres, avançando pela duração real do serviço. Não há registros de slots, nem dependência da antiga grade de 15 minutos. O servidor aceita qualquer início em minuto inteiro que caiba integralmente em uma janela aberta, sem sobreposição. Períodos adjacentes formam uma janela contínua; intervalos fechados não podem ser atravessados.

A confirmação revalida conta, tenant, oferta ativa, duração, preço, horário futuro e disponibilidade. Uma cotação assinada evita confirmar silenciosamente preço/duração diferentes dos apresentados. Horários locais inexistentes ou ambíguos por mudança de fuso são rejeitados.

Confirmação, cancelamento e configuração de períodos usam a mesma trava transacional no profissional. Uma exclusion constraint PostgreSQL protege os intervalos confirmados com semântica `[início, fim)`, inclusive contra escritas simultâneas. FKs compostas asseguram que cliente, oferta, profissional e reserva pertençam ao tenant correto. Uma restrição no banco garante que a duração corresponda ao intervalo.

Editar ou fechar períodos não pode deixar reservas confirmadas fora da disponibilidade. A reserva cancelada permanece no histórico e libera o horário. Desativar catálogo ou profissional não apaga reservas; a agenda administrativa mantém uma lista textual dos atendimentos confirmados mesmo se o profissional estiver inativo.

## Instalação e verificação

Execute `myenv/bin/python manage.py migrate` antes de servir a versão com as novas rotas. Não é necessário recriar o banco.

- `myenv/bin/python manage.py test --noinput`
- `node painel/static/painel/agenda.test.cjs`
- `CHROME_EXECUTABLE=/opt/google/chrome/chrome myenv/bin/python scripts/qa_agenda.py`

O teste de navegador usa banco de testes descartável. Não rode junto com `manage.py test`. Os testes cobrem reservas simultâneas, isolamento, CSRF, conflitos, cancelamento, alterações de disponibilidade, fuso, cotação e o percurso cadastro → login → reserva → agenda administrativa → cancelamento.

## Agendamento pelo painel

Administradores do tenant acessam **+ Agendamento** no menu ou **+ Novo agendamento** na agenda diária. A rota `/painel/agendamentos/novo/` exige nome do cliente em texto e WhatsApp, além de profissional/serviço, data e horário. O acesso pela agenda preenche o dia e uma oferta do profissional selecionado; os campos podem ser alterados antes da confirmação.

O painel registra um contato sem conta de autenticação. Contatos do mesmo tenant com nome equivalente (sem diferença de maiúsculas ou espaços repetidos) e mesmo WhatsApp são reutilizados. A reserva aparece na agenda e na seção Clientes do painel. Nenhuma conta, e-mail ou senha é inventada. Um telefone informado pelo administrador não vincula automaticamente o atendimento a uma conta de login existente. Os agendamentos anteriores vinculados a contas continuam preservados.

A confirmação reutiliza as mesmas validações, cotação assinada e trava transacional do fluxo público. Contato e reserva são salvos na mesma transação: um conflito não deixa um contato sem reserva criado por essa tentativa. Não abre períodos automaticamente e não permite sobrepor reservas.

### Cancelamento administrativo

Na agenda diária, use **Cancelar agendamento** na lista de atendimentos ou nos detalhes de um bloco. A tela `/painel/agendamentos/<id>/cancelar/` mostra cliente, serviço, profissional, data e horário antes de confirmar por POST com CSRF. Apenas administradores do mesmo estabelecimento podem cancelar. A regra atual permite cancelamento antes do início do atendimento. A operação usa a trava do profissional, mantém o histórico, atualiza o estado na conta do cliente e libera o intervalo. GET nunca cancela e repetir o POST não altera novamente o registro já cancelado.

### Não compareceu

O administrador pode usar **Marcar falta** nos detalhes ou na lista da agenda após o horário inicial de um agendamento confirmado. Uma tela de confirmação grava o status `NAO_COMPARECEU` e o instante `nao_compareceu_em`. A operação exige POST com CSRF, valida tenant/permissão e usa a mesma trava transacional do profissional. Agendamentos futuros e cancelados não podem receber faltas. Repetir a ação preserva a primeira marcação.

A falta pertence ao atendimento, não altera o cadastro do cliente e não é marcada automaticamente pelo relógio. O atendimento permanece visível na agenda e no histórico do cliente como **Não compareceu**, mantendo o intervalo reservado para preservar seu histórico. Cancelamento e falta são estados distintos.

### Clientes no painel

O botão **Clientes** abre `/painel/clientes/`, com contatos, estado da conta e totais de agendamentos/faltas. A lista inclui clientes ativos e inativos, com ou sem histórico, além de contas que têm atendimentos mesmo após uma mudança de função. A busca aceita nome da conta, nomes registrados nos agendamentos, e-mail e WhatsApp parcial ou com formatação. Resultados e histórico são paginados; a busca é preservada ao trocar de página.

**Ver histórico** abre `/painel/clientes/<id>/`, com todos os estados, serviço, profissional, data, horário, valor, duração e datas de cancelamento/falta. Os nomes e valores dos atendimentos são os registrados na reserva. Somente administradores do mesmo tenant acessam essas páginas; contatos e históricos de outros estabelecimentos não aparecem.

Os contatos sem login também aparecem na lista paginada de 10 clientes, com busca por nome/WhatsApp e histórico em `/painel/clientes/contatos/<id>/`. A reserva exige exatamente uma identidade: conta de usuário ou contato de painel, com FKs compostas de tenant para ambos.
