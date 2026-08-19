# Deploying Ptah to Azure (UAE North)

Ptah runs on Azure Container Apps in **UAE North (Dubai)** with Azure Database
for PostgreSQL Flexible Server. This is a fresh deployment: the schema is built
by migrations and **no data is carried over from Heroku**.

Everything the app needs from a host is small — run gunicorn, reach a Postgres,
run `migrate` on deploy, and run one daily cron. There is no object storage:
uploaded CSVs are parsed in memory and never written to disk, and static files
are baked into the image and served by WhiteNoise.

## What you need before starting

| Requirement | Notes |
|---|---|
| Azure subscription with billing | Only you can create this and enter payment details |
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) | Or use the browser-based Azure Cloud Shell, which has it preinstalled |
| Docker Desktop | Optional. Only needed to run the app locally; deployment builds in Azure |
| A domain name | Optional but recommended, so you are not on an `azurecontainerapps.io` URL |

Expected running cost is roughly **$25-40/month** at this app's size. Verify
against current UAE North pricing before committing — regional prices differ
from the US list prices you may see quoted.

## 1. Sign in and set variables

```bash
az login
az account set --subscription "<your-subscription-id>"
```

```bash
RG=ptah-uae
LOCATION=uaenorth
REGISTRY=ptahuae            # must be globally unique, lowercase, no dashes
PG_SERVER=ptah-db           # must be globally unique
PG_ADMIN=ptahadmin
PG_PASSWORD='<generate-a-strong-one>'
ENVIRONMENT=ptah-env
APP=ptah-web
JOB_MIGRATE=ptah-migrate
JOB_SCRUB=ptah-scrub
```

Keep `PG_PASSWORD` in a password manager. It is only needed while provisioning;
afterwards the app reads it from a Container Apps secret.

## 2. Create the resource group and registry

```bash
az group create --name $RG --location $LOCATION
```

```bash
az acr create --resource-group $RG --name $REGISTRY --sku Basic --admin-enabled false
```

## 3. Create the database

Backups are **locally redundant on purpose**. Geo-redundant backups replicate
to a paired region outside the UAE, which would defeat the point of hosting
here at all.

```bash
az postgres flexible-server create \
  --resource-group $RG \
  --name $PG_SERVER \
  --location $LOCATION \
  --admin-user $PG_ADMIN \
  --admin-password "$PG_PASSWORD" \
  --tier Burstable \
  --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16 \
  --geo-redundant-backup Disabled \
  --backup-retention 14 \
  --public-access None \
  --yes
```

```bash
az postgres flexible-server db create \
  --resource-group $RG --server-name $PG_SERVER --database-name ptah
```

## 4. Create the Container Apps environment and app

```bash
az containerapp env create \
  --resource-group $RG --name $ENVIRONMENT --location $LOCATION
```

Build the first image (ACR builds it, so it is produced inside the region):

```bash
az acr build --registry $REGISTRY --image ptah:bootstrap --file Dockerfile .
```

Create the app. `--min-replicas 1` avoids cold starts on a workspace app that
staff use interactively.

```bash
az containerapp create \
  --resource-group $RG \
  --name $APP \
  --environment $ENVIRONMENT \
  --image $REGISTRY.azurecr.io/ptah:bootstrap \
  --registry-server $REGISTRY.azurecr.io \
  --system-assigned \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 --memory 1.0Gi
```

Grant the app permission to pull from the registry using its managed identity,
rather than storing registry credentials:

```bash
APP_IDENTITY=$(az containerapp show -g $RG -n $APP --query identity.principalId -o tsv)
ACR_ID=$(az acr show -g $RG -n $REGISTRY --query id -o tsv)
az role assignment create --assignee $APP_IDENTITY --role AcrPull --scope $ACR_ID
az containerapp registry set -g $RG -n $APP --server $REGISTRY.azurecr.io --identity system
```

## 5. Lock the database to the app only

The environment has a stable outbound IP; allow only that.

```bash
OUTBOUND_IP=$(az containerapp env show -g $RG -n $ENVIRONMENT \
  --query properties.staticIp -o tsv)

az postgres flexible-server firewall-rule create \
  --resource-group $RG --name $PG_SERVER \
  --rule-name containerapps \
  --start-ip-address $OUTBOUND_IP --end-ip-address $OUTBOUND_IP
```

To run `manage.py` commands from your own machine, add a temporary rule for
your IP and remove it afterwards:

```bash
MY_IP=$(curl -s https://api.ipify.org)
az postgres flexible-server firewall-rule create \
  --resource-group $RG --name $PG_SERVER --rule-name temp-admin \
  --start-ip-address $MY_IP --end-ip-address $MY_IP
# ... later ...
az postgres flexible-server firewall-rule delete \
  --resource-group $RG --name $PG_SERVER --rule-name temp-admin --yes
```

## 6. Set the application secrets

```bash
APP_FQDN=$(az containerapp show -g $RG -n $APP \
  --query properties.configuration.ingress.fqdn -o tsv)

DJANGO_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(64))")

DB_URL="postgres://$PG_ADMIN:$PG_PASSWORD@$PG_SERVER.postgres.database.azure.com:5432/ptah"
```

`sslmode` is deliberately not set: settings default it to `require` whenever
`DEBUG` is off, and Azure Postgres requires TLS.

```bash
az containerapp secret set -g $RG -n $APP \
  --secrets django-secret="$DJANGO_SECRET" database-url="$DB_URL"

az containerapp update -g $RG -n $APP \
  --set-env-vars \
    SECRET_KEY=secretref:django-secret \
    DATABASE_URL=secretref:database-url \
    DEBUG=False \
    TIME_ZONE=Asia/Dubai \
    ALLOWED_HOSTS=$APP_FQDN
```

## 7. Create the migration job

This is the release gate. The deploy workflow runs it to completion before
promoting a new revision, so a failed migration leaves the running version
untouched — the same protection the Heroku release phase gave us.

```bash
az containerapp job create \
  --resource-group $RG \
  --name $JOB_MIGRATE \
  --environment $ENVIRONMENT \
  --trigger-type Manual \
  --replica-timeout 900 \
  --replica-retry-limit 0 \
  --image $REGISTRY.azurecr.io/ptah:bootstrap \
  --registry-server $REGISTRY.azurecr.io \
  --system-assigned \
  --cpu 0.5 --memory 1.0Gi \
  --command "/bin/sh" --args "-c","python manage.py migrate --noinput" \
  --secrets database-url="$DB_URL" django-secret="$DJANGO_SECRET" \
  --env-vars SECRET_KEY=secretref:django-secret DATABASE_URL=secretref:database-url DEBUG=False
```

Grant it registry access the same way:

```bash
JOB_IDENTITY=$(az containerapp job show -g $RG -n $JOB_MIGRATE --query identity.principalId -o tsv)
az role assignment create --assignee $JOB_IDENTITY --role AcrPull --scope $ACR_ID
```

Run it once to build the schema:

```bash
az containerapp job start -g $RG -n $JOB_MIGRATE
```

## 8. Create the scheduled scrub job

Replaces Heroku Scheduler. Unlike Scheduler this is defined in code, not a
dashboard, so it can be reviewed and recreated.

```bash
az containerapp job create \
  --resource-group $RG \
  --name $JOB_SCRUB \
  --environment $ENVIRONMENT \
  --trigger-type Schedule \
  --cron-expression "0 2 * * *" \
  --replica-timeout 900 \
  --replica-retry-limit 1 \
  --image $REGISTRY.azurecr.io/ptah:bootstrap \
  --registry-server $REGISTRY.azurecr.io \
  --system-assigned \
  --cpu 0.5 --memory 1.0Gi \
  --command "/bin/sh" --args "-c","python manage.py scrub_expired_campaigns" \
  --secrets database-url="$DB_URL" django-secret="$DJANGO_SECRET" \
  --env-vars SECRET_KEY=secretref:django-secret DATABASE_URL=secretref:database-url DEBUG=False
```

```bash
SCRUB_IDENTITY=$(az containerapp job show -g $RG -n $JOB_SCRUB --query identity.principalId -o tsv)
az role assignment create --assignee $SCRUB_IDENTITY --role AcrPull --scope $ACR_ID
```

`0 2 * * *` is 02:00 UTC, which is 06:00 in Dubai. Cron here is always UTC.

## 9. Create the first user

```bash
az containerapp exec -g $RG -n $APP --command "python manage.py createsuperuser"
```

That account is a platform administrator with no organization, so it can reach
`/admin/` but not the tenant workspace. Create your actual workspace by
registering at `/Account/register/`.

## 10. Wire up GitHub Actions

Deployment uses OIDC, so no long-lived Azure credential is stored in GitHub.

```bash
SUBSCRIPTION=$(az account show --query id -o tsv)
APP_REG=$(az ad app create --display-name ptah-github-deploy --query appId -o tsv)
az ad sp create --id $APP_REG
az role assignment create --assignee $APP_REG --role Contributor \
  --scope /subscriptions/$SUBSCRIPTION/resourceGroups/$RG
```

Add the federated credential, replacing the branch if you deploy from another:

```bash
az ad app federated-credential create --id $APP_REG --parameters '{
  "name": "github-deploy",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:mohammedlnagar/ptah:ref:refs/heads/agent/ptah-domain-refactor",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

Then add three repository secrets in GitHub under
**Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | the `appId` printed above |
| `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |

Deploy from the **Actions** tab → *Deploy to Azure* → Run workflow, typing
`deploy` to confirm.

## 11. Custom domain

```bash
az containerapp hostname add -g $RG -n $APP --hostname app.yourdomain.ae
az containerapp hostname bind -g $RG -n $APP --hostname app.yourdomain.ae \
  --environment $ENVIRONMENT --validation-method CNAME
```

Then add the domain to `ALLOWED_HOSTS`. `CSRF_TRUSTED_ORIGINS` is derived from
it automatically, so no code change is needed:

```bash
az containerapp update -g $RG -n $APP \
  --set-env-vars ALLOWED_HOSTS=app.yourdomain.ae,$APP_FQDN
```

## Data residency notes

- **Backups are locally redundant.** Do not switch on geo-redundancy: the
  paired region for UAE North is outside the country.
- **The image is built by ACR inside UAE North**, not on a GitHub runner, so
  application code is assembled in-region. The source repository itself is on
  GitHub and therefore outside the UAE.
- **CI must never hold production data.** The test workflow seeds synthetic
  records against a throwaway Postgres; keep it that way.
- **WhatsApp is outside the UAE.** Every message an operator opens hands the
  patient's name and number to Meta. Hosting in UAE North does not change that,
  and it is likely the larger question in any compliance review.

## Running locally

```bash
docker compose up --build
```

The app comes up on http://localhost:8000 against a local Postgres, using the
same Python version as production.
