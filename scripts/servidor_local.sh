#!/usr/bin/env bash
# Ambiente local com as chaves públicas de teste do Cloudflare Turnstile.
# Não altera o .env nem as chaves usadas em produção.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export DJANGO_DEBUG=true
export TENANT_BASE_DOMAIN=localhost
export DEV_PUBLIC_HOST=''
export DEV_TENANT_SUBDOMAIN=''
export TURNSTILE_ENABLED=true
export TURNSTILE_VERIFY_HOSTNAME=true
export TURNSTILE_PUBLIC_SITE_KEY=1x00000000000000000000BB
export TURNSTILE_PUBLIC_SECRET_KEY=1x0000000000000000000000000000000AA
export TURNSTILE_AUTH_SITE_KEY=1x00000000000000000000AA
export TURNSTILE_AUTH_SECRET_KEY=1x0000000000000000000000000000000AA
local_port="${1:-8001}"
if [[ ! "$local_port" =~ ^[0-9]{1,5}$ ]] || (( 10#$local_port < 1024 || 10#$local_port > 65535 )); then
    echo 'Informe uma porta entre 1024 e 65535.' >&2
    exit 1
fi
exec myenv/bin/python manage.py runserver "127.0.0.1:$local_port"
