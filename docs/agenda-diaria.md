# Agenda diária dos profissionais

## Diagnóstico e decisões

A implementação anterior já armazenava janelas reais em `Disponibilidade`, com FK composta de tenant e exclusão GiST contra sobreposição. A interface, porém, mostrava uma lista de períodos de várias datas. Não havia JavaScript ou framework CSS: apenas os estilos locais dos templates.

O campo `Tenant.intervalo_grade_minutos` era usado no formulário de configuração, nos textos do painel e nos testes dessa configuração. Não participava das constraints de disponibilidade nem de cálculo de horários.

Esta reformulação preserva todos os models e as migrations aplicadas. **Nenhuma migration nova é necessária.** O campo da grade permanece no banco, com seus valores e constraint, mas foi descontinuado: não aparece no painel nem no admin global, e não influencia a linha do tempo. A rota antiga de configuração redireciona GET para a agenda e rejeita POST com 410, sem alterar o valor legado.

## Utilização

Acesse `/painel/agenda/` como ADMIN do estabelecimento.

1. Selecione o profissional nos cards superiores.
2. Escolha o dia usando as setas, Hoje ou o seletor de data.
3. Sem períodos ativos, a tela mostra **Agenda fechada**, sem uma falsa lista de horários disponíveis.
4. Clique **Abrir agenda**. Informe, por exemplo, 09:00–12:00 e 13:00–18:00, e salve.
5. A linha do tempo mostra os períodos **Livre** e o intervalo **Fechado** entre eles.
6. Em **Configurar horários**, ajuste, adicione ou remova períodos. Ao remover todos, a ação passa a ser **Fechar agenda**.

Todos os horários são locais ao timezone do tenant. O dia inicial é o dia atual nesse timezone. A seleção fica explícita na URL (`profissional` e `data`) e é sempre validada pelo servidor. Os links antigos de agenda individual continuam funcionando; sua navegação leva à nova tela central.

Profissionais inativos aparecem identificados e com agenda efetivamente fechada. Seus períodos não são apagados. As rotas individuais antigas de edição de disponibilidade também continuam disponíveis para compatibilidade, sem se tornar a navegação principal.

## Gravação e concorrência

O formulário envia pares início/fim, sem aceitar tenant ou IDs de disponibilidade. O profissional e a data vêm da rota validada; o tenant vem de `request.tenant`. A operação `agenda.services.configurar_dia`:

- trava o profissional e os períodos ativos do dia;
- confere a revisão dos períodos apresentada ao abrir o formulário;
- valida limites e sobreposição dos pares, com semântica `[início, fim)`;
- mantém IDs de períodos inalterados;
- desativa períodos removidos e cria somente os novos;
- confirma tudo em uma única transação.

Uma falha desfaz toda a configuração. Revisão desatualizada retorna conflito e pede recarregamento; alterações concorrentes não são sobrescritas silenciosamente. As constraints PostgreSQL continuam sendo a última proteção contra relações cruzadas e sobreposição. Datas diferentes, outros profissionais e registros inativos são preservados.

## Componente visual

Arquivos principais:

- `agenda/forms.py`: validação dos múltiplos períodos.
- `agenda/services.py`: configuração diária transacional e revisão.
- `agenda/presentation.py`: dados de apresentação dos intervalos reais.
- `painel/agenda_views.py`: seleção, estados aberta/fechada e configuração.
- `painel/templates/painel/agenda/`: tela diária e painel de edição.
- `painel/static/painel/agenda.css`: aparência responsiva com CSS local, sem framework adicional.
- `painel/static/painel/agenda.js`: modal, inclusão/remoção de períodos e componente reutilizável de linha do tempo.

A linha do tempo calcula posição e altura a partir de segundos reais, com escala visual independente de qualquer configuração de grade. As marcações de hora são criadas apenas no DOM. O banco não recebe slots.

`window.DailyAgenda.renderTimeline(element, payload)` permite instanciar componentes independentes, preparando uma visão futura com várias colunas. O payload real contém `appointments: []`; não há agendamentos fictícios na interface. Um futuro adaptador poderá fornecer:

```javascript
{
  professionalId: 123,
  date: '2026-09-30',
  timeZone: 'America/Sao_Paulo',
  windows: [{ start: 32400, end: 43200 }], // segundos locais do dia
  appointments: [{
    cliente: 'Nome do cliente', servico: 'Corte',
    inicio: '2026-09-30T09:30:00-03:00',
    fim: '2026-09-30T10:10:00-03:00',
    valor: '40,00', status: 'CONFIRMADO'
  }]
}
```

O componente converte os datetimes no timezone informado, dimensiona o bloco pela duração, retira a ocupação dos segmentos livres e usa texto além da cor. Blocos curtos mantêm sua altura real; os detalhes podem ser abertos por clique/teclado. Cancelados têm apresentação própria e não retiram disponibilidade. Isso é preparação visual, sem implementar model, confirmação ou regras de agendamento.

No celular há somente uma agenda visível; os cards de seleção podem rolar horizontalmente dentro do seu contêiner. O modal tem rótulos, foco inicial, contenção do Tab, fechamento com Escape e restauração de foco. Sem JavaScript, navegação/data e envio continuam no servidor, o editor abre como painel e os períodos aparecem como lista textual; a adição dinâmica de linhas exige JavaScript.

## Verificações

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test
node painel/static/painel/agenda.test.cjs
```

Testes da nova agenda cobrem datas/profissionais selecionados, estados, dois períodos, horários sem arredondamento, janelas adjacentes, sobreposição, fechamento, preservação de histórico, rollback, revisão desatualizada, IDs manipulados, autorização e CSRF. Os testes anteriores de integridade PostgreSQL e gravações concorrentes permanecem na suíte.

Para o teste opcional de navegador:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/qa_agenda.py
```

Se preferir o Chrome instalado, use `CHROME_EXECUTABLE=/caminho/do/chrome python scripts/qa_agenda.py`. O script usa o banco temporário de testes do Django e não deve rodar junto com `manage.py test`. Captura desktop/celular e verifica abertura, navegação, edição e erros. Screenshots ficam em `/tmp/agenda-qa` (ou em `QA_SCREENSHOTS`).

## Tema visual

O estilo compartilhado de autenticação, painel, cadastros e agenda fica em `usuarios/static/usuarios/theme.css`. Para trocar o verde, altere apenas:

```css
:root {
  --brand-color: #287454;
}
```

Os tons suaves, bordas, foco e hover são derivados dessa variável via `color-mix`. Uma futura configuração por tenant poderá sobrescrever `--brand-color` no elemento raiz, sem reescrever os componentes. Use uma cor suficientemente escura para manter a leitura dos botões com texto branco. Cores semânticas de erro, cancelamento e ocupação permanecem independentes.
