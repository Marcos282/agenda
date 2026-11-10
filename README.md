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

Na página principal da plataforma, telas de até 680 px exibem uma faixa flutuante “Agende conosco para conhecer melhor”, fixa na parte inferior da tela e ocupando toda a largura, com acesso ao WhatsApp +55 (21) 99092-1092. A faixa não aparece em telas maiores nem nas páginas dos estabelecimentos.

As páginas públicas da plataforma, início do estabelecimento e loja carregam a tag do Google Analytics `G-QNYYDDRTKK`, pelo componente `usuarios/google_tag.html`. O componente não é incluído na base compartilhada de login, conta, agendamentos e painel administrativo.

## Política de Privacidade

A URL pública `/politica-de-privacidade/` reutiliza o visual institucional, sem autenticação, CAPTCHA, Analytics ou contexto de estabelecimento. O documento é servido também em subdomínios, inclusive de estabelecimentos inativos ou inexistentes, desde que o Host seja permitido. Somente essa rota recebe a exceção no middleware: a autenticação e o isolamento das demais URLs permanecem inalterados. Os rodapés compartilham um link absoluto para `https://tacombinado.net/politica-de-privacidade/`.

O código integra o Turnstile à confirmação de agendamentos, ao login e ao cadastro de estabelecimentos. Sua ativação depende da configuração do ambiente. A data da política é uma data de versão fixa, não a data de cada acesso.

Antes de publicar, obter revisão e aprovação jurídica/operacional, sem presumir conformidade integral à LGPD:

- Confirmar que a razão social, o CNPJ e o e-mail já informados no rodapé institucional correspondem ao responsável pelo Tá Combinado e que esse canal receberá e atenderá pedidos de privacidade; definir o encarregado/responsável e divulgar seu contato quando aplicável.
- Validar o inventário de dados e as bases legais por finalidade, incluindo histórico de faltas/reputação, dados cadastrais publicados, cobrança, mensagens e métricas do Google Analytics. Avaliar mecanismos de consentimento/cookies exigíveis; esta alteração não os implementa.
- Documentar prazos e rotinas reais de retenção, exclusão, resposta aos titulares, incidentes e controles organizacionais. A política não promete backups, criptografia em repouso ou segurança absoluta não comprovados.
- Confirmar fornecedores ativos de hospedagem, WhatsApp/Evolution, e-mail/Resend, pagamentos/Mercado Pago e métricas/Google, contratos, compartilhamentos e eventuais transferências internacionais com suas garantias.
- Formalizar os papéis de controlador/operador por operação e revisar o texto e a ativação do Turnstile antes da publicação.

Validação focada: `python manage.py check` e `python manage.py test usuarios.test_privacidade usuarios.test_privacidade_browser`. O teste de navegador usa Playwright e `/usr/bin/google-chrome`, conforme os testes de UI existentes, e bloqueia requisições externas.

Regressão adicional: `TENANT_BASE_DOMAIN=localhost DEV_PUBLIC_HOST='' DEV_TENANT_SUBDOMAIN='' EVOLUTION_API_URL='' EVOLUTION_API_KEY='' python manage.py test usuarios.tests usuarios.test_home usuarios.test_registro usuarios.test_login_platform usuarios.test_ngrok agenda.test_guest_booking agenda.test_booking`. Essas variáveis valem somente para o processo de teste: as suítes legadas usam `*.localhost`, não o domínio de produção, e a integração externa de WhatsApp deve ficar desabilitada na validação.

## Testar o Turnstile localmente

Para testar em `*.localhost`, sem modificar o `.env`, execute o servidor com as chaves públicas de teste documentadas pela [Cloudflare](https://developers.cloudflare.com/turnstile/troubleshooting/testing/):

```bash
DJANGO_DEBUG=true TURNSTILE_ENABLED=true TURNSTILE_VERIFY_HOSTNAME=true \
TURNSTILE_PUBLIC_SITE_KEY=1x00000000000000000000BB \
TURNSTILE_PUBLIC_SECRET_KEY=1x0000000000000000000000000000000AA \
TURNSTILE_AUTH_SITE_KEY=1x00000000000000000000AA \
TURNSTILE_AUTH_SECRET_KEY=1x0000000000000000000000000000000AA \
python manage.py runserver 127.0.0.1:8791
```

Essas chaves e o token de teste não fornecem proteção real. Apenas com `DEBUG=true`, hostname local e conexão de loopback, o backend aceita a resposta específica de teste da Cloudflare, que usa `example.com` e não contém `action`; a API Siteverify continua sendo consultada. Tokens reais continuam sujeitos à verificação de `action`, hostname e uso único. Em produção, o Turnstile permanece obrigatório: use as quatro chaves reais, mantenha a verificação de hostname ativa e nunca utilize essas chaves de teste. Configurações que tentem desativar a proteção ou a conferência de hostname geram erros no `manage.py check`.

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

O hero dos estabelecimentos apresenta título, descrição, resumo do catálogo e arte, sem os botões "Explorar serviços" e "Conhecer a equipe". A navegação para serviços e profissionais permanece no cabeçalho; os cards continuam dando acesso ao agendamento.

Em `/painel/estilo/conteudo/`, os dois campos de imagem existentes são reutilizados como **Banner Desktop** (`hero_image`, recomendado 1920x700 px) e **Banner Mobile** (`background_image`, recomendado 1080x1350 px). O desktop aparece somente acima de 768 px; o mobile, até 768 px inclusive. Ambos ocupam apenas a área da arte do hero, preservando o texto. Sem banner ativo para a largura atual, a arte padrão permanece. As opções de ativar, desativar, remover e visualizar continuam independentes; arquivos existentes não são migrados ou apagados.

A seleção usa `<picture>` com fontes por media query: o navegador solicita apenas o banner da largura atual no carregamento inicial. A imagem preenche a área com `object-fit: cover`, preservando a proporção (com recorte, sem distorção). Ao redimensionar a tela para a outra faixa, o navegador pode carregar o outro banner.

Em **Conteúdo do Site**, marque **Hero sem cor** para deixar o fundo transparente, sem degradê, borda colorida ou sombra, em qualquer estilo. A altura do hero, os banners e a logomarca são preservados. **Visualizar** permite testar sem gravar; **Salvar e aplicar** publica a opção. Desmarcar volta a usar a cor do estilo; restaurar a aparência original também desativa a transparência. No deploy, execute `python manage.py migrate` para aplicar a migração `0023_tenanttheme_hero_transparent`, além de `collectstatic` e reiniciar o serviço.

A rota `/` apresenta a plataforma no domínio raiz e o catálogo do estabelecimento em cada subdomínio. No domínio raiz, é possível encontrar um tenant ativo pelo seu identificador (por exemplo, `marcos`). Nos subdomínios, a página exibe somente profissionais, serviços e vínculos ativos do tenant atual, com valores/durações reais, sem formulário de busca ou filtro por profissional. Os links dos profissionais e a busca por URL continuam disponíveis. Contatos privados e fotos administrativas não são publicados.

O catálogo tem paginação e estados vazios. O fluxo de escolha de horários e confirmação de agendamento ainda não foi implementado; a página informa isso e oferece cadastro/login. O visual reutiliza `--brand-color` em `usuarios/static/usuarios/theme.css`; o layout da vitrine está em `usuarios/static/usuarios/home.css`.

Os cards de serviços exibem a foto do profissional da oferta em um avatar circular de 56 px no canto superior direito, com `object-fit: cover`. Sem foto cadastrada ou se a imagem não carregar, o avatar exibe a inicial do nome, seguindo o padrão da equipe.

A duração fica centralizada logo abaixo do avatar. Nome e valor ficam juntos na mesma linha, separados por um pequeno espaço fixo, sem linha divisória e sem distribuir o preço até a borda direita.

Cada card inteiro é um link para o agendamento da oferta, sem botão interno. O link funciona por clique, toque ou teclado, com foco visível e elevação discreta no hover; a animação respeita a preferência por movimento reduzido.

## Loja de serviços

Em `/loja/`, cada tenant tem uma vitrine própria, com cards de serviços, preço e duração por profissional, busca, filtros, ordenação e paginação. `/loja/<id>/` mostra os detalhes de uma oferta ativa do mesmo tenant. A página inicial possui um botão Loja. A vitrine usa o mesmo tema `--brand-color` e não exige migrations. Agendamento, carrinho de compras, checkout e pagamento não fazem parte desta entrega.

### Página comercial da plataforma

O domínio principal (`http://localhost:8000/`) apresenta a plataforma para donos de estabelecimentos. Os subdomínios continuam exibindo os serviços de cada tenant, incluindo sua loja em `/loja/`.

A página apresenta somente o Plano Profissional, com todas as funcionalidades e profissionais ilimitados. O preço mostrado e cobrado vem de `PLATFORM_MONTHLY_PRICE=30.00` (R$ 30,00/mês); os botões direcionam ao cadastro.

### Agendamentos online

O cliente pode agendar pela loja ou pelos serviços da página do estabelecimento. A confirmação exige apenas nome e WhatsApp e é automática, sem e-mail ou senha. Consulta e cancelamento ficam em `/agendamentos/` neste navegador e no link pessoal mostrado na confirmação. As reservas aparecem na agenda administrativa. Antes de iniciar o servidor atualizado, execute `myenv/bin/python manage.py migrate`. Detalhes em [docs/agendamentos.md](docs/agendamentos.md).

### WhatsApp dos clientes

O cadastro público exige WhatsApp com DDD. Números brasileiros são salvos com `+55`; números de outros países devem ser informados com `+` e código do país. O cliente pode atualizar o contato em `/conta/`.

Contas anteriores sem WhatsApp são preservadas. Ao entrar, o cliente é direcionado para completar o cadastro; novas reservas, inclusive pelo painel, exigem esse contato. Consultas e cancelamentos de reservas existentes continuam disponíveis. A validação confere o formato do telefone; não verifica a existência de uma conta WhatsApp nem envia mensagens.

A confirmação do agendamento também exibe WhatsApp obrigatório, preenchido com o contato da conta. Enviar vazio ou inválido bloqueia a reserva, mesmo quando a conta já possui um número. Correções do número são salvas junto com a reserva, na mesma transação.

No agendamento pelo painel, informe o nome do cliente em texto e o WhatsApp obrigatório. Não é exigida conta do cliente; um contato é registrado com seu histórico na seção Clientes. Agendamentos públicos também aceitam nome e WhatsApp sem login.

### WhatsApp e lembretes de agendamento

O painel possui configuração por estabelecimento, conexão Evolution API por QR code e mensagem de lembrete com antecedência ajustável (padrão: 2 horas). Consulte [configuração e execução periódica](docs/whatsapp.md) para ativar o envio automático.

Para respostas `1` (confirmar presença) e `2` (cancelar), consulte [confirmação e cancelamento pelo WhatsApp](docs/whatsapp-respostas.md), incluindo migração, webhook autenticado e processamento de retornos.

### QR Code da loja

No painel, o botão **QR Code da loja**, ao lado de **WhatsApp**, mostra o QR Code do endereço público do estabelecimento (por exemplo, `https://marcos.tacombinado.net/`). É possível baixar a imagem PNG para compartilhar ou imprimir. O domínio público é configurado por `STORE_BASE_DOMAIN` (padrão: `tacombinado.net`), independente do endereço local usado para acessar o painel. A imagem é gerada no próprio servidor, sem serviços externos.

### Acesso ao sistema por 30 dias

O botão **Acesso ao sistema**, ao lado do QR Code da loja, permite comprar 30 dias do Plano Profissional pelo Checkout Pro do Mercado Pago, sem assinatura ou cobrança automática. `PLATFORM_MONTHLY_PRICE=30.00` define a mensalidade de R$ 30,00/mês. O acesso é renovado após a confirmação do pagamento, preservando os dias restantes. Cada estabelecimento começa com 30 dias grátis; após o vencimento, novos agendamentos ficam pausados e o administrador pode acessar a página de renovação. A migração do plano antigo preserva vencimentos e histórico financeiro, sem cobranças adicionais. Consulte [configuração e testes](docs/mensalidade.md).

## Limite diário por cliente

Em **Painel → Meu cadastro → Agendamentos por cliente**, o administrador define o máximo de reservas por WhatsApp por data de atendimento (padrão: 2). O limite soma os serviços de todos os profissionais do estabelecimento no fuso local. Reservas confirmadas e faltas contam; canceladas liberam espaço. Outros dias e estabelecimentos têm contagens independentes.

A reserva registra o WhatsApp utilizado para preservar a identificação mesmo que o cadastro mude depois. As migrações preenchem as reservas anteriores com o número disponível no cadastro. Ao atingir o limite, o cliente recebe uma mensagem para escolher outra data ou cancelar uma reserva.

- [Plano Profissional único, migração e publicação](docs/planos-estabelecimento.md)

- [Mensalidade, confirmação Mercado Pago e comprovantes](docs/pagamentos-mensalidade.md)
