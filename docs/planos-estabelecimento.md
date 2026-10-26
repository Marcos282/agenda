# Plano único por estabelecimento

O Tá Combinado oferece somente o **Plano Profissional**, com todas as funcionalidades
existentes: profissionais e agendas ilimitados, agendamentos online, WhatsApp,
histórico de clientes, loja online, personalização e QR Code.

O preço mensal é definido exclusivamente pela configuração existente:

```dotenv
PLATFORM_MONTHLY_PRICE=30.00
```

Com essa configuração, a página pública de preços, o cadastro e o painel mostram
**R$ 30,00/mês**. O Django Admin também mostra a mensalidade configurada e permite
somente o Profissional para estabelecimentos. `PLATFORM_ACCESS_PRICE` não participa
do cálculo. Valores enviados pelo navegador não definem o preço ou o tenant.
Valores inválidos de configuração são rejeitados explicitamente.

## Cadastro e renovação

Todos os novos estabelecimentos começam no Profissional, com os 30 dias iniciais
gratuitos já existentes. O cadastro não cria checkout nem pagamento.

O sistema existente usa **pagamento avulso pelo Checkout Pro do Mercado Pago**,
sem assinatura recorrente ou débito automático. O botão **Renovar por 30 dias**
cria ou reutiliza a preferência. Abrir o checkout não acrescenta dias nem altera
o vencimento. Cada pagamento aprovado e validado concede 30 dias uma única vez,
contados de `max(hoje no fuso do estabelecimento, vencimento atual)`.

Cliques repetidos reutilizam o checkout válido do mesmo estabelecimento, preço,
plano, ambiente e URL de retorno. Checkouts pagos, expirados, com preço diferente
ou de plano antigo não são reutilizados para novas compras. A chave de idempotência
e os bloqueios transacionais existentes permanecem.

## Migração e histórico

O plano antigo limitado é identificado como `INDIVIDUAL` (Plano Individual) no
banco deste projeto. Ele deixa de ser uma opção de contratação.

A migração [0021_plano_unico](../tenants/migrations/0021_plano_unico.py):

- Atualiza todos os tenants antigos para `PROFISSIONAL`, inclusive os inativos.
- Altera apenas o plano: preserva vencimento, datas de cadastro/atualização,
  estado do estabelecimento, profissionais, agendas e histórico.
- Remove os triggers PostgreSQL que limitavam profissionais ativos.
- Restringe novos registros e atualizações de tenants ao Profissional.
- Não consulta o Mercado Pago, cria preferências, confirma pagamentos ou cobra.
- É idempotente. A reversão de schema não restaura a classificação antiga dos
  tenants; um rollback dos dados exige o backup anterior à publicação.

A migração [0005_checkout_profissional_default](../pagamentos/migrations/0005_checkout_profissional_default.py)
altera somente o padrão para novos checkouts. Checkouts e pagamentos históricos
mantêm plano adquirido, valor, IDs Mercado Pago, status e datas. O identificador
legado continua disponível para exibição dos comprovantes, não para contratação.

Pagamentos de checkouts antigos podem chegar depois da migração. A confirmação
continua verificando o **valor original da cobrança**, e não a mensalidade atual.
Quando aprovados, renovam uma única vez e mantêm o tenant no Profissional,
sem desativar profissionais nem exigir pagamentos complementares.

## Publicação

Faça backup do banco, mantenha as credenciais Mercado Pago e configure
`PLATFORM_MONTHLY_PRICE=30.00` no ambiente do servidor. Pause os processos da
aplicação durante a aplicação das migrations para evitar gravações pelo código
antigo enquanto o schema é atualizado.

```bash
cd /var/www/html/combinado
git pull --ff-only
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart combinado
```

As migrations devem preceder a inicialização do novo código. Nenhuma mudança
no webhook, cron ou configuração de contratos Mercado Pago é necessária.

## Verificação

```bash
TENANT_BASE_DOMAIN=localhost DJANGO_DEBUG=true myenv/bin/python manage.py test tenants.test_plans pagamentos painel.test_mensalidade usuarios.test_registro usuarios.test_home --noinput
myenv/bin/python manage.py makemigrations --check --dry-run
```

Com Playwright e o Chrome em `/usr/bin/google-chrome`, a verificação das telas
em desktop e mobile pode ser executada separadamente:

```bash
TENANT_BASE_DOMAIN=localhost DJANGO_DEBUG=true myenv/bin/python manage.py test painel.test_single_plan_browser --noinput
```

Os testes usam o SDK simulado, sem cobranças reais. Cobrem cadastro, preço
configurável em todas as interfaces, rejeição de planos antigos, renovação,
webhooks, comprovantes legados, idempotência, concorrência e migração real no
PostgreSQL. O teste de migração compara todos os campos dos tenants (exceto
plano), profissionais, checkouts e pagamentos antes/depois, incluindo pendências,
e confirma que não há chamadas ao SDK.

Detalhes dos callbacks e comprovantes: [pagamentos-mensalidade.md](pagamentos-mensalidade.md).
