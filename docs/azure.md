# Deploying Ptah to Azure (UAE North)

Ptah runs on Azure Container Apps in **UAE North (Dubai)** with Azure Database
for PostgreSQL Flexible Server. The database has **no public endpoint**: it
lives inside a virtual network and is reachable only from the Container Apps
environment. Application secrets live in Key Vault and are read by managed
identity, so the database password appears in no application configuration.

Everything the app needs from a host is small — run gunicorn, reach a Postgres,
run `migrate` on deploy, and run one daily cron. There is no object storage:
uploaded CSVs are parsed in memory and never written to disk, and static files
are baked into the image and served by WhiteNoise.

Every command below has been run for real against this subscription. Where the
obvious form of a command does not work, the reason is noted.

## What is deployed

| Resource | Name |
|---|---|
| Resource group | `ptah-uae` (UAE North) |
| Virtual network | `ptah-vnet` — `snet-apps` /23, `snet-db` /28 |
| Database | `ptah-db-uae`, VNet-injected, no public endpoint |
| Private DNS zone | `ptahprivate.postgres.database.azure.com` |
| Container registry | `ptahuae.azurecr.io` (Basic, admin disabled) |
| Key Vault | `ptah-kv-uae01` (RBAC authorisation) |
| Environment | `ptah-env`, VNet-integrated |
| Web app | `ptah-web` |
| Jobs | `ptah-migrate` (manual), `ptah-scrub` (daily 02:00 UTC) |

## What you need before starting

| Requirement | Notes |
|---|---|
| Azure subscription with billing | Only you can create this and enter payment details |
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) | Or the browser-based Azure Cloud Shell, which has it preinstalled |
| Docker Desktop | Optional. Only needed to run the app locally; deployment builds in Azure |
| A domain name | Optional but recommended, so you are not on an `azurecontainerapps.io` URL |

Expected running cost is roughly **$25-40/month** at this size. The VNet is
free; the private DNS zone is about $0.50/month. Verify against current UAE
North pricing — regional prices differ from the US list prices usually quoted.

## Before you start: two local gotchas

**TLS-intercepting antivirus breaks the CLI.** If `az` fails with
`CERTIFICATE_VERIFY_FAILED`, something is re-signing HTTPS traffic. Norton's
"Web/Mail Shield" does this, and its root certificate has `Basic Constraints`
not marked critical, which modern OpenSSL rejects outright — so adding it to a
CA bundle does not help. Turn off the product's SSL/TLS scanning, or run these
commands from [Azure Cloud Shell](https://shell.azure.com) instead. The same
interception also breaks `docker build` locally, for the same reason.

**Set UTF-8 before long-running commands.** On a Windows console `az acr build`
can crash with `'charmap' codec can't encode characters` while streaming build
logs. The build keeps running in Azure; only the log stream dies.

```bash
export PYTHONIOENCODING=utf-8      # PowerShell: $env:PYTHONIOENCODING = "utf-8"
```

If it does crash, check the build with:

```bash
az acr task list-runs --registry ptahuae --top 3 --output table
```

## 1. Sign in and register providers

```bash
az login
az account set --subscription "<your-subscription-id>"
```

Registration takes a few minutes and everything after it fails without it:

```bash
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry \
          Microsoft.DBforPostgreSQL Microsoft.KeyVault; do
  az provider register --namespace $ns
done
```

```bash
RG=ptah-uae
LOCATION=uaenorth
REGISTRY=ptahuae            # globally unique, lowercase, no dashes
PG_SERVER=ptah-db-uae       # globally unique
VAULT=ptah-kv-uae01         # globally unique
DNS_ZONE=ptahprivate.postgres.database.azure.com
PG_ADMIN=ptahadmin
PG_PASSWORD='<generate-a-strong-one>'
```

## 2. Resource group, network and registry

```bash
az group create --name $RG --location $LOCATION
```

The apps subnet must be **/23** — a Consumption environment rejects anything
smaller. Each subnet is delegated to the service that will occupy it.

```bash
az network vnet create -g $RG -n ptah-vnet --location $LOCATION \
  --address-prefixes 10.20.0.0/16 \
  --subnet-name snet-apps --subnet-prefixes 10.20.0.0/23

az network vnet subnet update -g $RG --vnet-name ptah-vnet -n snet-apps \
  --delegations Microsoft.App/environments

az network vnet subnet create -g $RG --vnet-name ptah-vnet -n snet-db \
  --address-prefixes 10.20.2.0/28 \
  --delegations Microsoft.DBforPostgreSQL/flexibleServers
```

```bash
az acr create -g $RG -n $REGISTRY --sku Basic --location $LOCATION --admin-enabled false
```

## 3. Private DNS zone

Create the zone yourself rather than letting the server command generate one.
The zone name **may not be the server name plus the suffix** — Azure rejects
that — and the `.private.` infix used with private endpoints is not accepted
here either. A plain distinct label works.

```bash
az network private-dns zone create -g $RG -n $DNS_ZONE

az network private-dns link vnet create -g $RG -n ptah-dns-link \
  --zone-name $DNS_ZONE --virtual-network ptah-vnet --registration-enabled false
```

## 4. Database, with no public endpoint

Backups are **locally redundant on purpose**: geo-redundant backups replicate
to a paired region outside the UAE, which would defeat hosting here.

Pass `--subnet` as a full resource ID *on its own*. Mixing a `--vnet` name with
a `--subnet` ID is rejected, and omitting `--private-dns-zone` is rejected too.

```bash
SUBNET_DB=$(az network vnet subnet show -g $RG --vnet-name ptah-vnet -n snet-db --query id -o tsv)
ZONE_ID=$(az network private-dns zone show -g $RG -n $DNS_ZONE --query id -o tsv)

az postgres flexible-server create \
  --resource-group $RG --name $PG_SERVER --location $LOCATION \
  --admin-user $PG_ADMIN --admin-password "$PG_PASSWORD" \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
  --geo-redundant-backup Disabled --backup-retention 14 \
  --subnet $SUBNET_DB --private-dns-zone $ZONE_ID \
  --yes
```

`--name` is the *database* and `--server-name` the server:

```bash
az postgres flexible-server db create -g $RG --server-name $PG_SERVER --name ptah
```

```bash
az postgres flexible-server parameter set -g $RG --server-name $PG_SERVER \
  --name ssl_min_protocol_version --value TLSv1.2
```

There are **no firewall rules** and none are needed. The server has no public
endpoint at all; a rule would have nothing to permit.

> A public server restricted by firewall rules does **not** work as a
> substitute. A Consumption environment's `staticIp` is its *inbound* address —
> outbound traffic leaves via dynamic Azure addresses, so a single-IP rule can
> never match. The only alternative is allowing all Azure services, which lets
> any Azure tenant reach the endpoint.

## 5. Build the image

```bash
az acr build --registry $REGISTRY --image ptah:bootstrap --image ptah:latest --file Dockerfile .
```

## 6. Key Vault

```bash
az keyvault create -g $RG -n $VAULT --location $LOCATION --enable-rbac-authorization true

ME=$(az ad signed-in-user show --query id -o tsv)
VAULT_ID=$(az keyvault show -g $RG -n $VAULT --query id -o tsv)
az role assignment create --assignee $ME --role "Key Vault Secrets Officer" --scope $VAULT_ID
```

The password is URL-encoded inside the connection string (`@` becomes `%40`,
`!` becomes `%21`, and so on) or the URL will not parse. `sslmode` is omitted
deliberately: settings default it to `require` whenever `DEBUG` is off.

```bash
az keyvault secret set --vault-name $VAULT --name django-secret-key \
  --value "$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"

az keyvault secret set --vault-name $VAULT --name database-url \
  --value "postgres://$PG_ADMIN:<url-encoded-password>@$PG_SERVER.postgres.database.azure.com:5432/ptah"
```

## 7. Environment and web app

```bash
SUBNET_APPS=$(az network vnet subnet show -g $RG --vnet-name ptah-vnet -n snet-apps --query id -o tsv)

az containerapp env create -g $RG -n ptah-env --location $LOCATION \
  --infrastructure-subnet-resource-id $SUBNET_APPS
```

Ingress stays **external** so staff reach the app over the internet; only the
database is private.

```bash
az containerapp create -g $RG -n ptah-web --environment ptah-env \
  --image $REGISTRY.azurecr.io/ptah:bootstrap \
  --registry-server $REGISTRY.azurecr.io --registry-identity system \
  --system-assigned \
  --target-port 8000 --ingress external \
  --min-replicas 1 --max-replicas 3 --cpu 0.5 --memory 1.0Gi
```

Grant the app's identity read access to the vault, then point its secrets at
Key Vault rather than storing values inline:

```bash
APP_ID=$(az containerapp show -g $RG -n ptah-web --query identity.principalId -o tsv)
az role assignment create --assignee $APP_ID --role "Key Vault Secrets User" --scope $VAULT_ID

VAULT_URI=$(az keyvault show -g $RG -n $VAULT --query properties.vaultUri -o tsv | sed 's:/*$::')
FQDN=$(az containerapp show -g $RG -n ptah-web --query properties.configuration.ingress.fqdn -o tsv)

az containerapp secret set -g $RG -n ptah-web --secrets \
  "django-secret=keyvaultref:$VAULT_URI/secrets/django-secret-key,identityref:system" \
  "database-url=keyvaultref:$VAULT_URI/secrets/database-url,identityref:system"

az containerapp update -g $RG -n ptah-web --set-env-vars \
  SECRET_KEY=secretref:django-secret \
  DATABASE_URL=secretref:database-url \
  DEBUG=False TIME_ZONE=Asia/Dubai ALLOWED_HOSTS=$FQDN
```

## 8. Jobs

Define jobs in **YAML**, not with `--command` / `--args`. Passing arguments on
the command line through the Windows `az.cmd` wrapper mangles them into a
single string, and the job silently runs the wrong thing. Templates for both
jobs are in this repository under `infra/`.

```bash
az containerapp job create -g $RG -n ptah-migrate --environment ptah-env --yaml infra/job-migrate.yaml
az containerapp job create -g $RG -n ptah-scrub   --environment ptah-env --yaml infra/job-scrub.yaml
```

Each job has its own identity and needs its own grants:

```bash
ACR_ID=$(az acr show -g $RG -n $REGISTRY --query id -o tsv)
for job in ptah-migrate ptah-scrub; do
  PID=$(az containerapp job show -g $RG -n $job --query identity.principalId -o tsv)
  az role assignment create --assignee $PID --role "Key Vault Secrets User" --scope $VAULT_ID
  az role assignment create --assignee $PID --role AcrPull --scope $ACR_ID
done
```

Build the schema:

```bash
az containerapp job start -g $RG -n ptah-migrate
```

`ptah-scrub` runs `scrub_expired_campaigns` daily at `0 2 * * *`. Cron is always
UTC, so that is 06:00 in Dubai.

## 9. Create the first user

`createsuperuser` is interactive, so run it as a throwaway job with the
password supplied by environment variable, then delete the job so the
credential does not remain in Azure configuration. A template is in
`infra/job-createsu.yaml`.

That account is a platform administrator with no organization: it can reach
`/admin/` but not the tenant workspace. Create your actual workspace by
registering at `/Account/register/`.

## 10. Deploy from GitHub Actions

Deployment uses OIDC, so no long-lived Azure credential is stored in GitHub.

```bash
SUBSCRIPTION=$(az account show --query id -o tsv)
APP_REG=$(az ad app create --display-name ptah-github-deploy --query appId -o tsv)
az ad sp create --id $APP_REG
az role assignment create --assignee $APP_REG --role Contributor \
  --scope /subscriptions/$SUBSCRIPTION/resourceGroups/$RG
```

```bash
az ad app federated-credential create --id $APP_REG --parameters '{
  "name": "github-deploy",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:mohammedlnagar/ptah:ref:refs/heads/agent/ptah-domain-refactor",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

Add three repository secrets under **Settings → Secrets and variables →
Actions**: `AZURE_CLIENT_ID` (the `appId` above), `AZURE_TENANT_ID`
(`az account show --query tenantId -o tsv`) and `AZURE_SUBSCRIPTION_ID`.

Deploy from **Actions → Deploy to Azure → Run workflow**, typing `deploy` to
confirm. The workflow builds in ACR, runs `ptah-migrate` to completion, and
only then promotes the new revision — so a failed migration leaves the running
version serving.

## 11. Custom domain

```bash
az containerapp hostname add -g $RG -n ptah-web --hostname app.yourdomain.ae
az containerapp hostname bind -g $RG -n ptah-web --hostname app.yourdomain.ae \
  --environment ptah-env --validation-method CNAME
```

Add the domain to `ALLOWED_HOSTS`; `CSRF_TRUSTED_ORIGINS` is derived from it
automatically, so no code change is needed.

```bash
az containerapp update -g $RG -n ptah-web \
  --set-env-vars ALLOWED_HOSTS=app.yourdomain.ae,$FQDN
```

## Data residency notes

- **The database has no public endpoint.** It is reachable only from inside
  `ptah-vnet`, resolved through a private DNS zone.
- **Backups are locally redundant.** Do not switch on geo-redundancy: the
  paired region for UAE North is outside the country.
- **Secrets live in Key Vault** and are read by managed identity. The database
  password is in no application configuration.
- **The image is built by ACR inside UAE North**, not on a GitHub runner. The
  source repository is on GitHub and therefore outside the UAE.
- **CI must never hold production data.** The test workflow seeds synthetic
  records against a throwaway Postgres; keep it that way.
- **WhatsApp is outside the UAE.** Every message an operator opens hands the
  patient's name and number to Meta. Hosting here does not change that, and it
  is likely the larger question in any compliance review.

## Deliberately not done

- **ACR private endpoint** — needs the Premium tier, roughly +$45/month. The
  registry holds the application image, not patient data.
- **Microsoft Entra authentication for Postgres** instead of a password —
  stronger, but needs token-refresh handling in Django.
- **Front Door or WAF** — worth revisiting once a custom domain is in use.

## Running locally

```bash
docker compose up --build
```

The app comes up on http://localhost:8000 against a local Postgres, using the
same Python version as production.
