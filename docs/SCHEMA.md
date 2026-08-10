# Waslni tenant schema

Waslni uses shared PostgreSQL tables with strict organization foreign keys. An
employee belongs to at most one organization; an organization can employ many
users. Platform superusers are the only accounts allowed to have no
organization.

## Tenant and access models

- `Organization` owns all business data and the WhatsApp deep-link template.
- `SubscriptionPlan` defines commercial limits.
- `OrganizationSubscription` records one current subscription per organization.
- `CustomUser.organization` assigns an employee to one tenant.
- Django groups provide the `Owner`, `Admin`, `Approver`, and `Operator` roles.

## Campaign models

- `ImportBatch` audits every CSV upload and any corrective replacement.
- `Campaign` is an appointment-reminder or marketing list.
- `CampaignItem` is an immutable imported row snapshot. Appointment campaigns
  use only `booked`, `confirmed`, and `cancelled` statuses.
- `CampaignMessage` stores the rendered message snapshot and tracks whether the
  WhatsApp link was opened or the user marked the message as sent.
- `DoctorSummary` stores a shareable, campaign-specific doctor summary.

## Directory models

- `Department` and `Doctor` are organization-owned reference records.
- `Contact` is unique by `(organization, phone_number)` and, when supplied, by
  `(organization, mrn)`.
- `MessageTemplate` is organization-owned and follows a draft/approval flow.

All historical campaign rows and messages snapshot human-readable values so
later edits to contacts, doctors, departments, or templates cannot rewrite the
record of what was imported and prepared for sending.
