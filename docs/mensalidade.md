# Mensalidade e assinatura Mercado Pago

O botão **Mensalidade** fica disponível ao administrador do estabelecimento em `/painel/mensalidade/`. A integração cria uma assinatura recorrente a cada 30 dias por R$ 30,00 por tenant, usando o checkout hospedado do Mercado Pago. A aplicação não recebe nem armazena dados de cartão.

## Credenciais

Configure as variáveis abaixo no `.env` da raiz do projeto em desenvolvimento local. O arquivo é carregado pelo Django e ignorado pelo Git. Em produção, defina os mesmos nomes no ambiente do processo:

```dotenv
PLATFORM_MONTHLY_PRICE=30.00
MERCADO_PAGO_ACCESS_TOKEN=APP_USR-...
MERCADO_PAGO_WEBHOOK_SECRET=segredo-de-assinatura-do-webhook
```

Obtenha o Access Token nas credenciais da aplicação Mercado Pago (use credenciais de produção no servidor e de teste apenas localmente). Obtenha o segredo de assinatura em **Suas integrações → Webhooks**. Nunca coloque essas credenciais no HTML, JavaScript, repositório ou mensagens de suporte. O preço padrão é `30.00`; ele também precisa corresponder ao valor configurado no Mercado Pago.

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
