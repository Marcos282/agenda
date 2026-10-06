# Agendamento — fundação e gestão do estabelecimento

Lembretes automáticos de retorno: veja [configuração, confirmação de atendimento realizado e agendamento diário](docs/lembretes-retorno-30-dias.md).

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

## Página inicial pública

A rota `/` apresenta a plataforma no domínio raiz e o catálogo do estabelecimento em cada subdomínio. No domínio raiz, é possível encontrar um tenant ativo pelo seu identificador (por exemplo, `marcos`). Nos subdomínios, a página exibe somente profissionais, serviços e vínculos ativos do tenant atual, com valores/durações reais, busca e filtro por profissional. Contatos privados e fotos administrativas não são publicados.

O catálogo tem paginação e estados vazios. O fluxo de escolha de horários e confirmação de agendamento ainda não foi implementado; a página informa isso e oferece cadastro/login. O visual reutiliza `--brand-color` em `usuarios/static/usuarios/theme.css`; o layout da vitrine está em `usuarios/static/usuarios/home.css`.

## Loja de serviços

Em `/loja/`, cada tenant tem uma vitrine própria, com cards de serviços, preço e duração por profissional, busca, filtros, ordenação e paginação. `/loja/<id>/` mostra os detalhes de uma oferta ativa do mesmo tenant. A página inicial possui um botão Loja. A vitrine usa o mesmo tema `--brand-color` e não exige migrations. Agendamento, carrinho de compras, checkout e pagamento não fazem parte desta entrega.

### Página comercial da plataforma

O domínio principal (`http://localhost:8000/`) apresenta a plataforma para donos de estabelecimentos. Os subdomínios continuam exibindo os serviços de cada tenant, incluindo sua loja em `/loja/`.

Configure `PLATFORM_SALES_URL` no ambiente com o link comercial (por exemplo, WhatsApp ou formulário de contato). Sem essa variável, os botões direcionam para a apresentação dos recursos na própria página. A cor principal continua controlada por `--brand-color` em `usuarios/static/usuarios/theme.css`.

### Agendamentos online

O cliente pode agendar pela loja ou pelos serviços da página do estabelecimento. A confirmação exige apenas nome e WhatsApp e é automática, sem e-mail ou senha. Consulta e cancelamento ficam em `/agendamentos/` neste navegador e no link pessoal mostrado na confirmação. As reservas aparecem na agenda administrativa. Antes de iniciar o servidor atualizado, execute `myenv/bin/python manage.py migrate`. Detalhes em [docs/agendamentos.md](docs/agendamentos.md).

### WhatsApp dos clientes

O cadastro público exige WhatsApp com DDD. Números brasileiros são salvos com `+55`; números de outros países devem ser informados com `+` e código do país. O cliente pode atualizar o contato em `/conta/`.

Contas anteriores sem WhatsApp são preservadas. Ao entrar, o cliente é direcionado para completar o cadastro; novas reservas, inclusive pelo painel, exigem esse contato. Consultas e cancelamentos de reservas existentes continuam disponíveis. A validação confere o formato do telefone; não verifica a existência de uma conta WhatsApp nem envia mensagens.

A confirmação do agendamento também exibe WhatsApp obrigatório, preenchido com o contato da conta. Enviar vazio ou inválido bloqueia a reserva, mesmo quando a conta já possui um número. Correções do número são salvas junto com a reserva, na mesma transação.

No agendamento pelo painel, informe o nome do cliente em texto e o WhatsApp obrigatório. Não é exigida conta do cliente; um contato é registrado com seu histórico na seção Clientes. Agendamentos públicos também aceitam nome e WhatsApp sem login.

### WhatsApp e lembretes de agendamento

O painel possui configuração por estabelecimento, conexão Evolution API por QR code e mensagem de lembrete com antecedência ajustável (padrão: 2 horas). Consulte [configuração e execução periódica](docs/whatsapp.md) para ativar o envio automático.

### QR Code da loja

No painel, o botão **QR Code da loja**, ao lado de **WhatsApp**, mostra o QR Code do endereço público do estabelecimento (por exemplo, `https://marcos.tacombinado.net/`). É possível baixar a imagem PNG para compartilhar ou imprimir. O domínio público é configurado por `STORE_BASE_DOMAIN` (padrão: `tacombinado.net`), independente do endereço local usado para acessar o painel. A imagem é gerada no próprio servidor, sem serviços externos.

### Acesso ao sistema por 30 dias

O botão **Acesso ao sistema**, ao lado do QR Code da loja, permite comprar 30 dias pelo Checkout Pro do Mercado Pago, sem assinatura ou cobrança automática. O preço padrão é R$ 30,00. O acesso é renovado após a confirmação do pagamento, preservando os dias restantes. Cada estabelecimento começa com 30 dias grátis; após o vencimento, novos agendamentos ficam pausados e o administrador pode acessar a página de renovação. Consulte [configuração e testes](docs/mensalidade.md).

## Limite diário por cliente

Em **Painel → Meu cadastro → Agendamentos por cliente**, o administrador define o máximo de reservas por WhatsApp por data de atendimento (padrão: 2). O limite soma os serviços de todos os profissionais do estabelecimento no fuso local. Reservas confirmadas e faltas contam; canceladas liberam espaço. Outros dias e estabelecimentos têm contagens independentes.

A reserva registra o WhatsApp utilizado para preservar a identificação mesmo que o cadastro mude depois. As migrações preenchem as reservas anteriores com o número disponível no cadastro. Ao atingir o limite, o cliente recebe uma mensagem para escolher outra data ou cancelar uma reserva.
