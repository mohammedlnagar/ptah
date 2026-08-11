# Ptah domain architecture

Ptah uses one PostgreSQL schema with row-level tenant ownership. Every tenant-owned
record has an `organization_id`, application queries are organization-scoped, model
validation rejects cross-organization relations, and `audit_tenant_integrity` checks
the stored graph. Organizations do not receive separate PostgreSQL schemas.

## Django apps

- `account`: organizations, employees, roles, and authentication.
- `directory`: contacts, doctors, departments, and normalized identity resolution.
- `appointments`: appointments and immutable appointment-status history.
- `imports`: upload batches and structured file/row validation issues.
- `campaigns`: appointment or marketing lists, immutable row snapshots, and doctor summaries.
- `messaging`: templates, immutable template revisions, rendered messages, and manual WhatsApp handoff events.
- `reporting`: campaign and doctor metric generation.
- `rasel`: HTTP workflow, forms, CSV orchestration, and templates retained for URL compatibility.
- `common`: shared timestamp, tenant query, validation, and admin primitives.

The domain ownership migrations use `SeparateDatabaseAndState`. Existing `rasel_*`
PostgreSQL table names remain in place, so the reorganization does not copy, rename,
or recreate campaign, directory, import, or messaging data.

## Status semantics

- Appointment: `booked`, `confirmed`, or `cancelled`.
- Message: `pending`, `opened`, `operator_marked_sent`, or `skipped`.

`opened` means Ptah opened the organization's WhatsApp URL. `operator_marked_sent`
means a user recorded the outcome manually. Neither state claims WhatsApp delivery.

## Tenant integrity

Run this after migrations and before a deployment is promoted:

```bash
python manage.py audit_tenant_integrity
```
