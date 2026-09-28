# Levantamento e recuperação — Etapa 1

Inspeção realizada em 27/09/2026 (America/Sao_Paulo), antes de alterar o banco.

O diretório continha somente `manage.py`, o pacote de configuração `barbe`, e os ambientes `myenv` e `.venv`. Não havia apps locais, arquivos de migrations ou repositório Git. `myenv` possuía Django 6.1.1 e psycopg 3.3.6; `.venv` possuía apenas pip.

`AUTH_USER_MODEL` já apontava para `usuarios.User`, sem que `usuarios` estivesse instalado/existisse. Por isso até `manage.py check` falhava. O banco PostgreSQL `barbe` estava acessível e já tinha migrations registradas:

- `tenants.0001_initial`;
- `usuarios.0001_initial`;
- `usuarios.0002_alter_user_managers_cliente`;
- `usuarios.0003_remove_cliente_uniq_cliente_tenant_user_and_more`;
- migrations padrão de auth, contenttypes, admin e sessions.

O esquema foi inspecionado diretamente via catálogo PostgreSQL, incluindo colunas, nulabilidade, tipos, unicidades, FKs e índices. As tabelas `tenants_tenant`, `usuarios_user`, `usuarios_cliente` e as relações de grupos/permissões de usuários estavam vazias. `usuarios_user` já possuía e-mail único, sem username, mas não tinha tenant ou tipo. `usuarios_cliente` possuía tenant e relação única com user.

## Recuperação compatível

Como os arquivos originais não estavam disponíveis, as migrations históricas foram **reconstruídas a partir do esquema final observado**, mantendo os nomes registrados. Não são uma recuperação literal do código original: `0002` representa diretamente a tabela Cliente em seu estado final e `0003` é uma migration sem operações. Em um banco novo, essa sequência produz o mesmo esquema-base relevante; no banco existente, essas migrations permanecem marcadas como aplicadas, sem repetir DDL nem usar `--fake`.

As novas migrations adicionam tenant/tipo ao usuário, constraints de tenant, e-mail e tipos, índices e uma FK composta entre Cliente e User. Essa FK protege inclusive operações bulk/SQL e alterações do tenant de um usuário com cliente associado. A tabela Cliente e os campos first_name/last_name existentes foram preservados. Não foram criados fluxos, formulários ou páginas de negócio de clientes.

A migration `usuarios.0004` verifica novamente se existem usuários antigos antes de alterar a tabela. Caso existam, ela interrompe e solicita mapeamento explícito usuário → tenant. Isso evita assumir um tenant para registros existentes em outro ambiente. Não executar reset, apagar banco ou usar fake como atalho.

A configuração local de senha do PostgreSQL e chave Django foi preservada em `.local-settings.json`, com permissão 0600 e ignorada pelo Git. Variáveis de ambiente têm precedência. Nenhuma senha foi colocada na documentação ou nos novos arquivos de configuração versionáveis.
