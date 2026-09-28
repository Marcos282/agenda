# Agendamento — fundação e gestão do estabelecimento

Django + PostgreSQL compartilhado, isolamento explícito por tenant e autenticação por e-mail. As Etapas 1 e 2 entregam autenticação, profissionais, catálogo, preço/duração por profissional e janelas de disponibilidade. O agendamento do cliente é uma etapa futura.

Veja o [guia da agenda diária](docs/agenda-diaria.md) para usar `/painel/agenda/` e o [guia da Etapa 2](docs/etapa-2.md) para os demais cadastros em `/painel/`.

## Executar no ambiente atual

O ambiente Python com as dependências instaladas é `myenv`:

```bash
source myenv/bin/activate
pip install -r requirements.txt
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py criar_tenants_dev
python manage.py test
python manage.py runserver
```

Acesse:

- http://marcos.localhost:8000
- http://wanessa.localhost:8000
- http://sofia.localhost:8000

Em cada host: `/cadastro/`, `/login/`, `/conta/` e logout via botão POST. Cadastro pede e-mail, senha e confirmação. Após cadastrar, entre pela tela de login. Se o sistema operacional não resolver `*.localhost`, adicione `127.0.0.1 marcos.localhost wanessa.localhost sofia.localhost` ao arquivo hosts.

`criar_tenants_dev` é idempotente: não altera tenants existentes, incluindo os inativos. O domínio raiz exibe a página da plataforma e não oferece cadastro/login de clientes.

## Instalação em outro ambiente

Use Python 3.12+ e um PostgreSQL acessível:

```bash
python -m venv myenv
source myenv/bin/activate
pip install -r requirements.txt
export DB_NAME=barbe
export DB_USER=postgres
export DB_PASSWORD='sua-senha-local'
export DB_HOST=127.0.0.1
export DB_PORT=5432
```

Crie previamente um banco vazio chamado `barbe` com seu usuário PostgreSQL. O comando `test` cria e remove **somente seu banco de teste**, por padrão `test_barbe`; o usuário precisa de permissão CREATEDB. Nenhum teste usa SQLite. Execute os comandos da seção anterior para aplicar as migrations.

No ambiente original, `.local-settings.json` preserva a conexão previamente configurada; não versione esse arquivo. Variáveis de ambiente têm precedência. Para outro domínio configure `TENANT_BASE_DOMAIN` (por exemplo, `exemplo.com`). `DJANGO_DEBUG=false` exige `DJANGO_SECRET_KEY` própria e ativa cookies seguros; nesse modo, use HTTPS. O proxy deve preservar o Host original validado; o app não confia em `X-Forwarded-Host`.

## Segurança e administração

- O middleware resolve apenas subdomínios diretos ativos de `TENANT_BASE_DOMAIN`; host inexistente/inativo retorna 404. O timezone do tenant vale durante a requisição e é restaurado depois.
- Cadastro atribui `request.tenant` e tipo CLIENTE no servidor. Campos adicionais enviados pelo navegador não controlam tenant ou privilégios.
- Login verifica e-mail, senha, usuário ativo e tenant. Toda requisição autenticada verifica novamente o tenant, mesmo que alguém copie manualmente uma sessão para outro host.
- Cookies de sessão e CSRF são restritos ao host. Logout aceita POST com CSRF; não se aceita redirecionamento externo via `next` nos fluxos de clientes.
- E-mails são normalizados com strip/lower. PostgreSQL exige e-mail normalizado, unicidade global sem distinção de maiúsculas, tipo válido e tenant obrigatório para usuários normais.
- A única exceção sem tenant é o superusuário global, que exige is_staff e tipo ADMIN. Ele não pode usar as áreas dos estabelecimentos. Crie com `python manage.py createsuperuser` (e-mail e senha, sem username), e acesse `http://localhost:8000/admin/`. Esse admin permite gerir tenants e alterar o campo Tipo dos usuários de tenant; os demais campos e os superusuários permanecem somente para consulta. ADMIN de tenant acessa `/painel/` em seu subdomínio e não recebe acesso à administração global.

Para criar um administrador de tenant pelo shell, use o manager e leia a senha sem registrá-la no histórico:

```python
from getpass import getpass
from tenants.models import Tenant
from usuarios.models import User
User.objects.create_user(
    email="gestor@exemplo.com",
    password=getpass("Senha: "),
    tenant=Tenant.objects.get(subdomain="marcos"),
    tipo=User.Tipo.ADMIN,
)
```

## Regras para os próximos módulos

Cada tabela operacional deve ter FK `tenant`, atribuída a partir de `request.tenant`. Filtre **toda** consulta operacional por esse tenant, inclusive buscas por PK (`get_object_or_404(Model, pk=pk, tenant=request.tenant)`). O middleware protege a identidade da sessão, mas não substitui filtros nas consultas. Para rotas privadas, use `@tenant_required` e `@login_required`.

Relações operacionais devem ser validadas na aplicação e protegidas com FKs compostas `(referencia_id, tenant_id)` quando necessário. A relação legada Cliente → User já usa esse mecanismo em `usuarios.0005`, com chave referenciada única `(id, tenant_id)` e verificação na aplicação. O ORM não representa essa FK composta, portanto ela é mantida explicitamente via `RunSQL` reversível.

A Etapa 2 implementa Profissional, Servico, ProfissionalServico e Disponibilidade. A agenda começa fechada e armazena apenas janelas explícitas. Para as próximas etapas: manter Cliente 1:1 User; permitir User opcional no Profissional; copiar preço/duração para Agendamento e protegê-lo contra sobreposição concorrente no PostgreSQL. O agendamento do cliente ainda não foi implementado.

## Verificação e histórico

Os testes cobrem os três hosts, cadastro e manipulação de campos, autenticação sem username, hashing, sessões cruzadas, inatividade, unicidade e constraints PostgreSQL, relação legada entre tenants, CSRF, logout e administração global.

Consulte [o diagnóstico inicial e a recuperação das migrations](docs/estado-inicial.md) antes de aplicar em outro banco que já possua dados. Os arquivos históricos estavam ausentes; a reconstrução preserva o esquema encontrado e não pretende reproduzir operações intermediárias desconhecidas.

Referências: [autenticação customizada do Django](https://docs.djangoproject.com/en/6.0/topics/auth/customizing/) e [constraints de modelos](https://docs.djangoproject.com/en/6.0/ref/models/constraints/).
