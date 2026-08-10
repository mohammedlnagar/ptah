# Staging migration rehearsal

Use a staging environment and a recent production database copy before merging the
tenant-schema pull request. Never rehearse the first migration on the only production
database copy.

## 1. Prepare staging

1. Back up the source database and verify that the backup can be restored.
2. Restore it into an isolated staging database.
3. Deploy the feature branch to an application that cannot send real customer messages.
4. Set fresh staging values for `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, and
   `TIME_ZONE`. Do not reuse production credentials.

## 2. Run the deployment gate

```bash
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py audit_tenant_integrity
python manage.py collectstatic --noinput
python manage.py test account rasel
```

Stop the deployment if any command fails. `audit_tenant_integrity` checks employee and
subscription ownership plus every cross-model organization relationship used by
campaigns, imports, messages, doctors, and summaries. It exits unsuccessfully and
prints sample primary keys when it finds an inconsistency.

## 3. Reconcile migrated data

- Confirm every non-platform user belongs to exactly one organization.
- Review the generated legacy organization, its subscription, and assigned users.
- Compare pre- and post-migration totals for users, contacts, lists/campaigns,
  appointment rows, templates, and rendered messages.
- Confirm legacy appointment states were mapped only to `booked`, `confirmed`, or
  `cancelled`.

## 4. Tenant-isolation smoke test

1. Create two staging organizations and one operator in each.
2. Upload an appointment CSV and a marketing CSV for both organizations.
3. Verify each operator sees only their own contacts, templates, doctors, campaigns,
   messages, filters, exports, and summaries.
4. Copy a campaign, message, item, and contact URL from one organization and request it
   while signed in to the other organization. Every request must return not found or
   forbidden without changing data.
5. Test Owner, Admin, Approver, and Operator permissions, including template approval.
6. Open WhatsApp links only with staging numbers and verify that opening a link does not
   mark the message as sent until an operator records that status.

## 5. Production release

After the rehearsal passes, mark the pull request ready for review. Take a fresh
production backup immediately before deployment, install dependencies, run the same
deployment gate, and monitor application and database logs throughout the rollout.
