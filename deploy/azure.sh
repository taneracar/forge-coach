#!/usr/bin/env bash
# Deploys forge-coach to Azure Container Apps on the consumption plan.
#
# Before running: `az login`, and put SUPABASE_URL, SUPABASE_ANON_KEY and
# ANTHROPIC_API_KEY in .env (gitignored). The image comes from GHCR, built by CI
# on every push to main. Safe to run again: later runs update the app in place.
#
# Scales to zero when idle. One replica at most, because the report cache lives
# in process memory. Logs stream through `az containerapp logs show`; they are
# not sent to Log Analytics, which bills per GB.
set -euo pipefail

cd "$(dirname "$0")/.."

RESOURCE_GROUP="${RESOURCE_GROUP:-forge-coach-rg}"
LOCATION="${LOCATION:-westus2}"
ENVIRONMENT="${ENVIRONMENT:-forge-coach-env}"
APP="${APP:-forge-coach}"
IMAGE="${IMAGE:-ghcr.io/taneracar/forge-coach:latest}"

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${SUPABASE_URL:?SUPABASE_URL is missing from .env}"
: "${SUPABASE_ANON_KEY:?SUPABASE_ANON_KEY is missing from .env}"
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY is missing from .env}"

az extension add --name containerapp --upgrade --only-show-errors
az provider register --namespace Microsoft.App --wait
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

if ! az containerapp env show --name "$ENVIRONMENT" --resource-group "$RESOURCE_GROUP" \
  --output none 2>/dev/null; then
  az containerapp env create \
    --name "$ENVIRONMENT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --logs-destination none \
    --output none
fi

ENV_VARS=(
  "SUPABASE_URL=$SUPABASE_URL"
  "SUPABASE_ANON_KEY=secretref:supabase-anon-key"
  "ANTHROPIC_API_KEY=secretref:anthropic-api-key"
)
SECRETS=(
  "supabase-anon-key=$SUPABASE_ANON_KEY"
  "anthropic-api-key=$ANTHROPIC_API_KEY"
)

if az containerapp show --name "$APP" --resource-group "$RESOURCE_GROUP" \
  --output none 2>/dev/null; then
  az containerapp secret set --name "$APP" --resource-group "$RESOURCE_GROUP" \
    --secrets "${SECRETS[@]}" --output none
  az containerapp update --name "$APP" --resource-group "$RESOURCE_GROUP" \
    --image "$IMAGE" --set-env-vars "${ENV_VARS[@]}" --output none
else
  az containerapp create \
    --name "$APP" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT" \
    --image "$IMAGE" \
    --ingress external \
    --target-port 8080 \
    --cpu 0.25 \
    --memory 0.5Gi \
    --min-replicas 0 \
    --max-replicas 1 \
    --secrets "${SECRETS[@]}" \
    --env-vars "${ENV_VARS[@]}" \
    --output none
fi

FQDN="$(az containerapp show --name "$APP" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn --output tsv)"

echo "Deployed: https://$FQDN"
for _ in $(seq 1 30); do
  if curl -fsS "https://$FQDN/health"; then
    echo
    exit 0
  fi
  sleep 5
done

echo "The app did not answer /health. Logs:" >&2
az containerapp logs show --name "$APP" --resource-group "$RESOURCE_GROUP" --tail 50 >&2
exit 1
