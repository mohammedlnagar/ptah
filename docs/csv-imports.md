# CSV import contract

CSV files must be UTF-8 encoded. A byte-order mark is accepted. Header names are
trimmed, while values are normalized before validation. An upload is represented by
one `ImportBatch`; a corrected file creates a separate replacement batch.

## Appointment reminders

Required columns:

- `Patient Name`
- `Patient Mobile`
- `Appointment Date/Time`
- `Consultant`

Optional columns:

- `MR No.` — the patient's Medical Record Number (MRN)
- `Doctor Department`
- `Appointment Status` — `booked`, `confirmed`, or `cancelled`; blank defaults to `booked`
- `Remarks`
- `Appointment ID` or `Appointment No.`

`Appointment Date` may still be present in older files, but is not required because
`Appointment Date/Time` is the authoritative value.

## Marketing

Required columns:

- `Patient Name`
- `Patient Mobile`

`MR No.` is optional.

Phone numbers must contain 7–15 digits. Invalid files create a failed import batch
and structured `ImportIssue` rows; they do not create a partial campaign.

## Template placeholders

Supported placeholders are:

- `#patient_name`
- `#mrn`
- `#doctor`
- `#department`
- `#appointment_date`
- `#appointment_time`
- `#appointment_status`

Unknown placeholders are rejected when the template form is validated.
