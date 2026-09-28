# Etapa 2 — profissionais, catálogo e disponibilidade

Atualização: a agenda agora possui [uma interface diária visual](agenda-diaria.md). A configuração de grade foi descontinuada e preservada apenas no banco por compatibilidade.

## Estado inicial e migração

Antes de implementar, foram revisados Tenant, User, o middleware, backend de autenticação, views, constraints/migrations e os testes. As migrations da Etapa 1 estavam aplicadas; os 19 testes existentes passaram no PostgreSQL. A autenticação e o isolamento existentes foram reutilizados. Nenhuma migration anterior foi alterada; nenhum banco ou dado de negócio foi apagado/recriado.

Novos apps:

- `profissionais`: Profissional, com contatos e foto opcionais, sem login próprio.
- `catalogo`: Servico e ProfissionalServico.
- `agenda`: apenas Disponibilidade (janelas), sem slots e sem agendamentos.
- `painel`: interface do ADMIN de tenant, formulários, autorização e testes de integração.

Novas migrations: `tenants.0003`, `profissionais.0001`, `catalogo.0001–0002`, `agenda.0001–0002`. A migration da agenda instala `btree_gist`; o usuário PostgreSQL precisa poder criar a extensão ou ela deve ser instalada previamente pelo administrador do banco. Não é utilizado SQLite.

```bash
source myenv/bin/activate
pip install -r requirements.txt
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py test
python manage.py runserver
```

Pillow foi incluído para validar e processar fotos.

## Entrar como administrador

Use uma conta `User` com `tipo=ADMIN` e tenant correspondente ao subdomínio. O cadastro público continua criando somente CLIENTE. Para criar um administrador pelo shell, siga o exemplo no README (`User.objects.create_user`, senha lida com `getpass`). Se a conta já existir, entre como superusuário global em `http://localhost:8000/admin/usuarios/user/`, abra o usuário, confira seu tenant, selecione **Tipo → Administrador** e salve. Não se atribuem privilégios automaticamente.

Entre em `http://marcos.localhost:8000/login/` e use o link **Painel**, ou acesse diretamente `http://marcos.localhost:8000/painel/`. CLIENTE e PROFISSIONAL recebem 403 no painel. O superusuário global continua restrito ao domínio raiz e ao `/admin/` da plataforma.

## Fluxo manual

1. Em **Profissionais**, crie João e Sandro. Cada agenda começa fechada.
2. Em **Serviços**, crie Corte e Barba. O catálogo não tem preço/duração.
3. No profissional João, abra **Serviços → Adicionar serviço**: Corte, R$ 40,00, 30 minutos.
4. No profissional Sandro, adicione Corte, R$ 40,00, 40 minutos; e Barba, R$ 20,00, 20 minutos.
5. Em **João → Agenda → Abrir período**, crie 30/09/2026, 09:00–12:00 e 14:00–18:00.
6. Em **Sandro → Agenda**, crie 30/09/2026, 08:00–13:00.
7. Na **Agenda**, selecione a data e o profissional. Use **Configurar horários** para editar vários períodos de uma vez. Não há exigência de encaixe em uma grade fixa.
8. Para desativar qualquer registro, abra **Editar**, desmarque **Ativo** e salve. Os registros permanecem armazenados.

As listagens são paginadas. Vínculos existentes preservam o serviço e o profissional: edite preço, duração e estado; não substitua o histórico por outro serviço. Para um novo serviço, crie outro vínculo. Um vínculo desativado continua ocupando a chave única profissional/serviço e pode ser reativado por edição.

## Regras adotadas

- Todas as quatro tabelas possuem tenant obrigatório com `PROTECT`. Formulários não expõem tenant. IDs do profissional vêm da rota e são buscados com tenant e, quando aplicável, com o pai correspondente.
- Valor é `DecimalField(10, 2)` e deve ser estritamente maior que zero; duração é um inteiro positivo. Não há grade fixa como regra de negócio.
- `ProfissionalServico` tem unicidade `(tenant, profissional, servico)`, inclusive para vínculos inativos.
- FKs compostas `(profissional_id, tenant_id)` e `(servico_id, tenant_id)` impedem relações cruzadas também em bulk/SQL e mudanças incompatíveis nos pais. São migrations `RunSQL` reversíveis, como na relação Cliente/User já existente.
- `hora_inicio < hora_fim`: uma janela não atravessa a meia-noite. Para atendimento que atravessa dias, um desenho explícito será necessário em etapa futura.
- Disponibilidades usam intervalo **[início, fim)**. 09:00–12:00 e 12:00–15:00 são válidos; 10:00–13:00 conflita com 09:00–12:00.
- Apenas janelas **ativas** participam da exclusão. Uma janela desativada não bloqueia novos períodos; reativá-la passa pelas mesmas validações e pode conflitar.
- A constraint PostgreSQL `disp_sem_sobreposicao` usa GiST/`btree_gist` e `tsrange(data + hora_inicio, data + hora_fim, '[)')`, agrupado por tenant/profissional. A proteção também vale sob concorrência e em atualizações diretas.
- As janelas representam data e hora locais do tenant. O cálculo futuro de instantes de agendamento deverá converter conforme o timezone e tratar transições de horário de verão quando aplicáveis.
- Novos vínculos e períodos exigem pais ativos; ativar registros também. Desativar um pai não apaga seus vínculos/períodos. As consultas `ProfissionalServico.objects.for_tenant(tenant).disponiveis()` e `Disponibilidade.objects.for_tenant(tenant).disponiveis()` excluem pais inativos. Reativar o pai torna novamente elegíveis seus filhos ainda ativos.
- A validação de pais ativos ocorre na aplicação. As operações do painel travam os pais durante a gravação para coordenar alterações concorrentes de estado. As constraints de tenant e sobreposição são garantias adicionais no banco.
- O painel não oferece exclusão física. FKs `PROTECT` impedem apagar pais com registros relacionados. Quando Agendamento for implementado, seus vínculos também deverão preservar o histórico.

## Fotos

Fotos opcionais aceitam imagens válidas de até 5 MB e 4096 × 4096 pixels. São recodificadas como JPEG sem metadados, com nomes aleatórios e diretório por tenant. A rota de leitura exige ADMIN do mesmo tenant; não há rota pública `/media/`. Em produção, mantenha esse armazenamento privado, sem mapear MEDIA_ROOT diretamente no servidor web.

Substituir/remover a referência da foto não apaga automaticamente o arquivo antigo do storage. A limpeza de arquivos órfãos deve ser feita separadamente, após conferir referências e backups.

## Testes

Além da regressão da Etapa 1, os testes cobrem autorização por papel, isolamento nos dois sentidos, GET/POST com IDs externos, associação ao pai incorreto dentro do mesmo tenant, campos injetados, catálogo ativo, desativação, edição, unicidade, dinheiro/duração/grade, fotos e CSRF.

A integridade é exercitada também sem `save()`/`full_clean()`, com bulk e updates, para verificar as constraints reais. Um teste com duas conexões/transações simultâneas tenta gravar períodos sobrepostos e exige um único commit.

Referência da implementação: [ExclusionConstraint no Django](https://docs.djangoproject.com/en/6.0/ref/contrib/postgres/constraints/).
