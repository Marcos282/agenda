# Mensalidade e assinatura Mercado Pago

O botão **Mensalidade** fica disponível ao administrador do estabelecimento em `/painel/mensalidade/`. A integração cria uma assinatura recorrente a cada 30 dias por R$ 30,00 por tenant, usando o checkout hospedado do Mercado Pago. A aplicação não recebe nem armazena dados de cartão.

## Credenciais

Configure as variáveis abaixo no `.env` da raiz do projeto em desenvolvimento local. O arquivo é carregado pelo Django e ignorado pelo Git. Em produção, defina os mesmos nomes no ambiente do processo:

```dotenv
PLATFORM_MONTHLY_PRICE=30.00
MERCADO_PAGO_ACCESS_TOKEN=APP_USR-...
MERCADO_PAGO_WEBHOOK_SECRET=segredo-de-assinatura-do-webhook
```

Obtenha o Access Token nas credenciais da aplicação Mercado Pago. Para cobranças reais, use a aplicação da conta recebedora real; para testar Assinaturas, siga a configuração específica abaixo. Obtenha o segredo de assinatura em **Suas integrações → Webhooks**. Nunca coloque essas credenciais no HTML, JavaScript, repositório ou mensagens de suporte. O preço padrão é `30.00`; ele também precisa corresponder ao valor configurado no Mercado Pago.

### Teste local em sandbox

Para Assinaturas, crie duas contas de teste no Mercado Pago: vendedor e comprador. Entre com o vendedor de teste, crie sua aplicação e use o Access Token das **credenciais de produção dessa conta de teste**, conforme a documentação do provedor. Um token com prefixo `APP_USR-` também pode pertencer a uma conta de teste; o prefixo sozinho não identifica o tipo da conta. Configure no `.env` local o token do vendedor de teste, o segredo do webhook da aplicação e o e-mail exato da conta compradora de teste:

```dotenv
MERCADO_PAGO_ACCESS_TOKEN=token-da-aplicacao-do-vendedor-de-teste
MERCADO_PAGO_WEBHOOK_SECRET=segredo-de-teste-do-webhook
MERCADO_PAGO_TEST_PAYER_EMAIL=email-da-conta-compradora-de-teste
```

O erro `Both payer and collector must be real or test users` indica mistura de contas reais e de teste. Confira também se o navegador está conectado ao comprador de teste ao concluir o checkout. Não use o e-mail do vendedor como comprador. Referência: [orientações oficiais para testar Assinaturas](https://www.mercadopago.com.br/developers/pt/news/2023/11/16/Questions-on-how-to-test-your-integration--).

`MERCADO_PAGO_TEST_PAYER_EMAIL` só é aplicado com `DEBUG=true`; fora do modo de desenvolvimento o sistema continua usando o e-mail do administrador autenticado. Não use credenciais ou contas reais para esse teste. O endpoint local não recebe webhooks diretamente da internet; validar a confirmação de pagamento exige expor o ambiente local por um túnel HTTPS e configurar a URL de webhook correspondente.

O domínio público precisa estar acessível por HTTPS. O checkout envia `notification_url` para `https://<subdomínio>.tacombinado.net/integracoes/mercado-pago/webhook/`. Em produção, configure `TENANT_BASE_DOMAIN=tacombinado.net` e mantenha `STORE_BASE_DOMAIN=tacombinado.net` (ou o domínio público efetivo) para que os webhooks cheguem ao tenant correto.

## Configuração de webhooks no Mercado Pago

Na aplicação do Mercado Pago, habilite notificações de **Assinaturas (preapproval)** e **Pagamentos autorizados de assinatura**. Use o segredo de assinatura da mesma aplicação em `MERCADO_PAGO_WEBHOOK_SECRET`. O endpoint valida `x-signature` com HMAC-SHA256 e consulta os dados do evento pela API autenticada antes de alterar qualquer prazo. Respostas não disponíveis são retornadas como erro temporário para permitir nova tentativa do provedor.

## Ciclo de acesso

- O cadastro inicia 30 dias grátis, contabilizados pela data local do estabelecimento.
- O painel mostra os dias restantes. No dia da expiração ele indica “Expira hoje”; o bloqueio começa no dia seguinte.
- Após o vencimento, o administrador pode entrar somente na tela **Mensalidade** do painel. As demais rotas administrativas redirecionam para lá.
- A loja pública pode continuar exibindo o catálogo, mas novos agendamentos são temporariamente bloqueados. Consultas e cancelamentos de reservas já existentes continuam acessíveis.
- Uma cobrança só renova o acesso depois de confirmada como aprovada pela API do Mercado Pago. Cada pagamento é registrado por ID único, portanto webhooks repetidos não duplicam a renovação.
- Cada cobrança aprovada acrescenta 30 dias à data de expiração atual quando o pagamento ocorre antes do vencimento. Se o prazo já venceu, os 30 dias começam a contar da data local do pagamento.
- A assinatura fica vinculada ao tenant por referência externa, e seu status é atualizado por webhook. O administrador pode continuar ou gerenciar a assinatura no Mercado Pago.

É necessária a migration `tenants.0006_mercado_pago_subscription`; aplique as migrations antes de iniciar a versão atualizada:

```bash
myenv/bin/python manage.py migrate
```

## Limites e operação

A aprovação depende de Access Token válido, preço configurado, webhook público HTTPS e segredo correspondente à aplicação do Mercado Pago. Sem essas configurações, o painel mantém o botão indisponível e não estende o prazo. Testes automatizados usam respostas simuladas e não iniciam cobranças reais.
