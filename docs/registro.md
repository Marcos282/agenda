# Registro de estabelecimentos e recuperação de senha

A página comercial possui o botão **Contratar**, que leva a `/registro` (também aceita `/registro/`). O formulário pede subdomínio, e-mail, senha e confirmação. O sufixo visual é `.tacombinado.net`.

O cadastro cria atomicamente um tenant ativo e seu usuário ADMIN, sem privilégios de superusuário/staff. O nome inicial do estabelecimento é o subdomínio. Não há cobrança ou integração de pagamento nesta etapa. Subdomínios reservados, inválidos ou duplicados e e-mails já utilizados são recusados. As senhas passam pelos validadores Django.

Após criar a conta, o botão de acesso usa o domínio `TENANT_BASE_DOMAIN`: em desenvolvimento, `seunegocio.localhost`; em produção, configure `TENANT_BASE_DOMAIN=tacombinado.net`. O usuário entra no subdomínio com seu e-mail e senha. A sessão não é compartilhada entre domínios. O DNS wildcard e o certificado dos subdomínios devem estar configurados em produção.

## Esqueci minha senha

Link disponível no registro e no login. `/lembrar-senha/` envia um link de uso único, válido por uma hora. Na raiz, a recuperação atende administradores dos estabelecimentos; no subdomínio, atende apenas contas daquele estabelecimento. Usuários/tenants inativos não recebem recuperação. A resposta é genérica para e-mails desconhecidos. O link não autentica automaticamente o usuário após trocar a senha.

Sem SMTP, o ambiente usa o backend de console: o e-mail fica no terminal/log do Django, sem entrega real. Configure as variáveis no processo Django para enviar mensagens reais:

```dotenv
EMAIL_HOST=smtp.seu-provedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=usuario-do-provedor
EMAIL_HOST_PASSWORD=senha-do-provedor
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=Tá Combinado <nao-responda@tacombinado.net>
```

TLS e SSL não devem ser ativados simultaneamente. O remetente precisa estar autorizado no provedor. Após alterar o ambiente, reinicie o Django/Gunicorn. Credenciais não devem ser versionadas. Nenhum e-mail real foi enviado nos testes.

### Provedor escolhido: Resend

A configuração específica do Resend está em [resend.md](resend.md). Com `RESEND_API_KEY` configurada, ele é selecionado automaticamente, sem precisar preencher EMAIL_HOST ou EMAIL_PORT.

## Login pela plataforma

O botão **Já sou cliente** abre `/login/` na raiz. O e-mail (único no sistema) identifica o estabelecimento. Após validar a senha, a plataforma encaminha o navegador ao subdomínio e abre o painel do administrador ou a conta do cliente, sem pedir a senha novamente.

A transferência usa um ticket opaco de uso único, com duração de 60 segundos, armazenado na tabela de sessões do Django e enviado por POST. A senha não é repassada ao subdomínio. O recebimento exige a origem exata da plataforma, revalida usuário/tenant/hash da senha e consome o ticket em transação. Cookies de autenticação continuam restritos ao host. Em produção o acesso entre domínios usa HTTPS; em desenvolvimento aceita os hosts locais. Links de login específicos de cada estabelecimento continuam funcionando.
