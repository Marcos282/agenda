# Abertura de agendas em lote

Acesso: **Painel → Agenda → Abrir agendas em lote**. Integra a própria view de
Agenda (`/painel/agenda/?lote=1`) e reutiliza `agenda.services.configurar_dia`.
Nesta revisão não havia uma interface de lote; não foi criada outra ferramenta
de administração nem um mecanismo paralelo de disponibilidade.

## Uso

1. Selecione um ou mais profissionais ativos do estabelecimento.
2. Escolha a data inicial e a quantidade de dias, de **1 a 7**, com padrão 7.
   A data é exibida e digitada em **dd/mm/aaaa**, com calendário do painel acima do botão Calendário. Os cartões também mostram a data brasileira completa.
   URLs, datas selecionadas e armazenamento continuam usando ISO (`aaaa-mm-dd`);
   o backend aceita o formato brasileiro e mantém compatibilidade com o anterior.
3. Marque as datas efetivas. Atalhos: todos, segunda a sexta, segunda a sábado
   ou limpar. Domingos e feriados podem ser marcados individualmente.
4. Ative manhã e/ou tarde e ajuste os horários. Não há sobreposição entre turnos.
5. Confira o resumo fixo e clique em **Confirmar abertura das agendas**.
6. A prévia informa configurações novas, existentes e sem alteração. Havendo
   horários anteriores, confirme explicitamente sua alteração no diálogo.

Ao entrar no lote pela Agenda, profissional e data selecionados são preservados
no botão de voltar e na seleção inicial. Após salvar, **Conferir agenda
configurada** abre o profissional e uma das datas efetivamente configuradas,
sem voltar silenciosamente para outro profissional ou para hoje.

O salvamento usa fetch e não recarrega a página. Há indicação de processamento,
diálogo nativo acessível por teclado, saída com Esc e mensagens de erro/sucesso.
O HTML também oferece prévia e confirmação quando JavaScript está indisponível.
Os estilos são restritos à tela e usam as variáveis e os componentes do painel,
sem dependências CSS novas. As cores acompanham variáveis de tema herdadas.

## Proteções

- Autenticação, papel ADMIN, tenant e CSRF são os mesmos da Agenda.
- O backend verifica quantidade inteira de 1 a 7, data inicial não passada no
  fuso do tenant, datas marcadas dentro do período e profissionais ativos locais.
- Somente os pares profissional/data marcados são afetados. Datas não marcadas
  e outros estabelecimentos permanecem intactos.
- Horários ativos e históricos inativos são considerados na prévia. Um dia
  anteriormente fechado por desativação de períodos exige confirmação antes
  de ser reaberto. Não é criada uma definição paralela de folga ou bloqueio.
- A prévia é assinada, vinculada ao tenant e aos parâmetros e válida por 15
  minutos. A revisão inclui períodos ativos/inativos e reservas nas datas.
  Alteração entre prévia e confirmação exige uma nova prévia.
- A operação toda é atômica; bloqueia tenant e profissionais em ordem. Falha
  em um dia desfaz o lote inteiro. Configurações iguais não são recriadas.
- O lote bloqueia qualquer alteração de horários em dias com reservas futuras
  ou em andamento, mesmo que o administrador marque a confirmação. Nenhum item
  do lote é aplicado nesse caso: desmarque essas datas ou use a configuração
  individual. Se os turnos forem exatamente iguais aos atuais, o dia é contado
  como sem alteração e não impede configurar outros dias vazios.
- Reservas existentes nunca são canceladas, movidas ou excluídas pelo lote.
  A configuração individual continua usando as proteções diárias existentes.

## Arquivos

- `painel/agenda_views.py`: entrada na Agenda existente.
- `painel/agenda_lote.py`: formulário, prévia assinada e transação de aplicação.
- `painel/templates/painel/agenda/dia.html`: botão de acesso.
- `painel/templates/painel/agenda/lote.html`: interface e confirmação.
- `painel/static/painel/agenda-lote.css`: estilos locais responsivos.
- `painel/static/painel/agenda-lote.js`: calendário, atalhos, resumo e envio.
- `painel/test_agenda_lote.py`: validação, isolamento, revisão e preservação.
- `painel/test_agenda_lote_browser.py`: fluxo real no Chrome e responsividade.

## Validação

Use PostgreSQL descartável e integrações externas desativadas:

```bash
python manage.py test painel.test_agenda_lote painel.test_agenda_lote_browser
python manage.py test agenda.test_booking agenda.test_opening_time
python manage.py check
python manage.py makemigrations --check --dry-run
```

Foram verificados os limites 1/7 e valores inválidos, datas fora do período,
profissionais estrangeiros/inativos, confirmação obrigatória, agenda fechada,
revisão alterada, reserva criada depois da prévia, atomicidade e reservas fora
dos turnos. O navegador verifica atalhos, marcação individual, contagem das
datas exibidas, confirmação, Esc, dimensões 320/390/768/1280 e cores herdadas.

Não exige migração nova. Nenhum deploy foi executado. Após a revisão e a
publicação autorizada, coletar estáticos e reiniciar a aplicação pelo processo
habitual do servidor. A funcionalidade usa dados do tenant atual e fica
disponível para estabelecimentos atuais e futuros sem cadastro manual no código.
