import datetime
import hashlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from django.db import transaction
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatusEvent
from campaigns.models import Campaign, CampaignItem
from directory.normalization import normalize_phone_number
from directory.services import resolve_contact, resolve_department, resolve_doctor
from imports.models import ImportBatch, ImportIssue
from messaging.formatting import format_message
from messaging.models import CampaignMessage, MessageTemplate
from reporting.services import refresh_campaign_summary


COMMON_REQUIRED_COLUMNS = {"Patient Name", "Patient Mobile"}
APPOINTMENT_REQUIRED_COLUMNS = {
    "Appointment Date/Time",
    "Consultant",
}


class CsvImportError(ValueError):
    def __init__(self, message, *, errors=None):
        super().__init__(message)
        self.errors = errors or [{"message": message}]


def _json_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _clean_optional(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _row_error(row_number, column, message):
    return CsvImportError(
        message,
        errors=[{"row": row_number, "column": column, "message": message}],
    )


def _normalize_phone(value, row_number):
    try:
        return normalize_phone_number(value)
    except Exception as exc:
        raise _row_error(
            row_number,
            "Patient Mobile",
            "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
        ) from exc


def _normalize_appointment_status(value, row_number):
    status = _clean_optional(value).lower()
    if not status:
        return Appointment.Status.BOOKED
    aliases = {
        "booked": Appointment.Status.BOOKED,
        "confirmed": Appointment.Status.CONFIRMED,
        "cancelled": Appointment.Status.CANCELLED,
        "canceled": Appointment.Status.CANCELLED,
    }
    if status not in aliases:
        raise _row_error(
            row_number,
            "Appointment Status",
            "Appointment status must be booked, confirmed, or cancelled.",
        )
    return aliases[status]


def _organization_timezone(organization):
    try:
        return ZoneInfo(organization.timezone)
    except ZoneInfoNotFoundError as exc:
        raise CsvImportError(
            f"The organization timezone '{organization.timezone}' is invalid."
        ) from exc


def _parse_appointment_datetime(value, row_number, organization_timezone):
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        raise _row_error(
            row_number,
            "Appointment Date/Time",
            "Enter a valid appointment date and time.",
        )
    scheduled_at = parsed.to_pydatetime()
    if timezone.is_naive(scheduled_at):
        scheduled_at = timezone.make_aware(scheduled_at, organization_timezone)
    return scheduled_at


def required_columns_for(purpose):
    required = set(COMMON_REQUIRED_COLUMNS)
    if purpose == Campaign.Purpose.APPOINTMENT:
        required.update(APPOINTMENT_REQUIRED_COLUMNS)
    return required


def _header_row_index(frame, required):
    """Return the index of the row that holds the column headers.

    Exported reports often carry a title block above the header and a totals
    row below the data, so the header is not always the first row. A row is
    treated as the header when it contains every required column name.
    """
    for index in range(len(frame)):
        values = {
            str(value).strip()
            for value in frame.iloc[index].tolist()
            if value is not None and not pd.isna(value)
        }
        if required.issubset(values):
            return index
    return None


def _drop_trailing_summary_rows(frame, required):
    """Drop trailing summary rows such as ``Total: 312 appointments``.

    Those rows fill a single cell and would otherwise fail per-row validation
    and reject the entire upload. A trailing row that fills two or more of the
    required columns is kept so that genuinely incomplete data is still
    reported to the operator rather than silently discarded.
    """
    while len(frame):
        last = frame.iloc[-1]
        populated = sum(
            1 for column in required if _clean_optional(last.get(column))
        )
        if populated > 1:
            break
        frame = frame.iloc[:-1]
    return frame


def clean_csv_data(file, purpose):
    """Return a frame of data rows indexed by their zero-based line in the file.

    The index is preserved rather than reset so validation errors can name the
    row the operator sees in their spreadsheet.
    """
    required = required_columns_for(purpose)
    try:
        file.seek(0)
        frame = pd.read_csv(file, dtype=str, header=None, encoding="utf-8-sig")
    except Exception as exc:
        raise CsvImportError(f"Unable to read CSV file: {exc}") from exc

    frame = frame.dropna(how="all")
    header_position = _header_row_index(frame, required)
    if header_position is None:
        # Report against the first row so the error names the columns that are
        # actually absent instead of failing generically.
        first_row = (
            [str(value).strip() for value in frame.iloc[0].tolist()]
            if len(frame)
            else []
        )
        missing = sorted(required.difference(first_row))
        raise CsvImportError(
            f"Missing columns: {', '.join(missing)}",
            errors=[
                {"column": column, "message": "This column is required."}
                for column in missing
            ],
        )

    header = frame.iloc[header_position]
    data = frame.iloc[header_position + 1 :].copy()
    data.columns = [str(value).strip() for value in header.tolist()]
    # Trailing separators produce unnamed columns; duplicates would make
    # row.get() return a Series instead of a scalar.
    data = data.loc[:, [column not in ("", "nan") for column in data.columns]]
    data = data.loc[:, ~data.columns.duplicated()]
    data = data.dropna(how="all")
    data = _drop_trailing_summary_rows(data, required)
    if data.empty:
        raise CsvImportError("The CSV contains no data rows.")
    return data


def prepare_csv_rows(frame, purpose, organization):
    prepared_rows = []
    errors = []
    organization_timezone = _organization_timezone(organization)

    for row_number, (source_index, row) in enumerate(frame.iterrows(), start=1):
        # clean_csv_data keeps the zero-based physical line as the index, so the
        # spreadsheet line number the operator sees is one greater.
        csv_row_number = int(source_index) + 1
        try:
            patient_name = _clean_optional(row.get("Patient Name"))
            if not patient_name:
                raise _row_error(
                    csv_row_number, "Patient Name", "Patient name is required."
                )
            phone = _normalize_phone(row.get("Patient Mobile"), csv_row_number)
            prepared = {
                "row_number": row_number,
                "csv_row_number": csv_row_number,
                "patient_name": patient_name,
                "phone": phone,
                "mrn": _clean_optional(row.get("MR No.")),
                "raw_data": {
                    str(key): _json_value(value) for key, value in row.items()
                },
                "doctor_name": "",
                "department_name": "",
                "scheduled_at": None,
                "appointment_status": None,
                "appointment_remarks": "",
                "external_reference": "",
            }
            if purpose == Campaign.Purpose.APPOINTMENT:
                doctor_name = _clean_optional(row.get("Consultant"))
                if not doctor_name:
                    raise _row_error(
                        csv_row_number,
                        "Consultant",
                        "Consultant name is required for appointment imports.",
                    )
                prepared.update(
                    {
                        "doctor_name": doctor_name,
                        "department_name": _clean_optional(
                            row.get("Doctor Department")
                        ),
                        "scheduled_at": _parse_appointment_datetime(
                            row.get("Appointment Date/Time"),
                            csv_row_number,
                            organization_timezone,
                        ),
                        "appointment_status": _normalize_appointment_status(
                            row.get("Appointment Status"), csv_row_number
                        ),
                        "appointment_remarks": _clean_optional(row.get("Remarks")),
                        "external_reference": _clean_optional(
                            row.get("Appointment ID")
                        )
                        or _clean_optional(row.get("Appointment No.")),
                    }
                )
            prepared_rows.append(prepared)
        except CsvImportError as exc:
            errors.extend(exc.errors)

    if errors:
        affected_rows = len({error.get("row") for error in errors if error.get("row")})
        raise CsvImportError(
            f"CSV validation failed on {affected_rows or 1} row(s).", errors=errors
        )
    return prepared_rows


def _mark_batch_failed(batch, error):
    batch.status = ImportBatch.Status.FAILED
    batch.error_count = max(len(error.errors), 1)
    batch.errors = error.errors
    batch.processed_at = timezone.now()
    batch.save(
        update_fields=(
            "status",
            "error_count",
            "errors",
            "processed_at",
            "updated_at",
        )
    )
    ImportIssue.objects.bulk_create(
        [
            ImportIssue(
                organization=batch.organization,
                batch=batch,
                row_number=issue.get("row"),
                column=issue.get("column", ""),
                code=issue.get("code", ""),
                message=issue.get("message", str(error))[:1000],
            )
            for issue in error.errors
        ]
    )


def _validate_import_scope(user, template, purpose, replaces):
    if not user.organization_id:
        raise CsvImportError("The user must belong to an organization.")
    if template.organization_id != user.organization_id:
        raise CsvImportError("The selected template belongs to another organization.")
    revision = template.current_revision
    approval_status = (
        revision.approval_status if revision else template.approval_status
    )
    if approval_status != MessageTemplate.ApprovalStatus.APPROVED:
        raise CsvImportError("Select an approved message template.")
    if not template.is_active:
        raise CsvImportError("Select an active message template.")
    if template.purpose not in {purpose, MessageTemplate.Purpose.GENERAL}:
        raise CsvImportError("The selected template does not match the campaign purpose.")
    if purpose not in Campaign.Purpose.values:
        raise CsvImportError("Invalid campaign purpose.")
    if replaces and (
        replaces.organization_id != user.organization_id
        or replaces.status != ImportBatch.Status.FAILED
    ):
        raise CsvImportError(
            "Only a failed import from this organization can be replaced."
        )


def save_campaign_from_csv(user, file, title, template, purpose, replaces=None):
    _validate_import_scope(user, template, purpose, replaces)
    template_revision = template.current_revision
    template_content = (
        template_revision.content if template_revision else template.content
    )

    file.seek(0)
    digest = hashlib.sha256(file.read()).hexdigest()
    file.seek(0)
    batch = ImportBatch.objects.create(
        organization=user.organization,
        uploaded_by=user,
        purpose=purpose,
        original_filename=file.name,
        sha256=digest,
        replaces=replaces,
    )

    try:
        frame = clean_csv_data(file, purpose)
        prepared_rows = prepare_csv_rows(frame, purpose, user.organization)
    except CsvImportError as exc:
        _mark_batch_failed(batch, exc)
        raise

    batch.status = ImportBatch.Status.VALIDATED
    batch.row_count = len(prepared_rows)
    batch.errors = []
    batch.error_count = 0
    batch.save(
        update_fields=(
            "status",
            "row_count",
            "errors",
            "error_count",
            "updated_at",
        )
    )

    retention_days = user.organization.campaign_retention_days
    try:
        with transaction.atomic():
            campaign = Campaign(
                organization=user.organization,
                title=title,
                purpose=purpose,
                import_batch=batch,
                template=template,
                template_revision=template_revision,
                created_by=user,
                status=Campaign.Status.READY,
                # Zero means the organization keeps patient details forever.
                scrub_after=(
                    timezone.now() + datetime.timedelta(days=retention_days)
                    if retention_days
                    else None
                ),
            )
            campaign.full_clean()
            campaign.save()

            for prepared in prepared_rows:
                contact = resolve_contact(
                    organization=user.organization,
                    name=prepared["patient_name"],
                    phone_number=prepared["phone"],
                    mrn=prepared["mrn"],
                )

                doctor = None
                appointment = None
                if purpose == Campaign.Purpose.APPOINTMENT:
                    department = None
                    if prepared["department_name"]:
                        department = resolve_department(
                            organization=user.organization,
                            name=prepared["department_name"],
                        )
                    if prepared["doctor_name"]:
                        doctor = resolve_doctor(
                            organization=user.organization,
                            name=prepared["doctor_name"],
                            department=department,
                        )
                    appointment = Appointment(
                        organization=user.organization,
                        contact=contact,
                        doctor=doctor,
                        source_import=batch,
                        external_reference=prepared["external_reference"],
                        scheduled_at=prepared["scheduled_at"],
                        status=prepared["appointment_status"],
                        remarks=prepared["appointment_remarks"],
                    )
                    appointment.full_clean()
                    appointment.save()
                    status_event = AppointmentStatusEvent(
                        organization=user.organization,
                        appointment=appointment,
                        previous_status="",
                        new_status=appointment.status,
                        changed_by=user,
                        reason="Created from CSV import.",
                    )
                    status_event.full_clean()
                    status_event.save()

                item = CampaignItem(
                    organization=user.organization,
                    campaign=campaign,
                    appointment=appointment,
                    contact=contact,
                    doctor=doctor,
                    row_number=prepared["row_number"],
                    patient_name_snapshot=prepared["patient_name"],
                    phone_number_snapshot=prepared["phone"],
                    mrn_snapshot=prepared["mrn"],
                    doctor_name_snapshot=prepared["doctor_name"],
                    department_name_snapshot=prepared["department_name"],
                    appointment_date=(
                        prepared["scheduled_at"].date()
                        if prepared["scheduled_at"]
                        else None
                    ),
                    appointment_time=(
                        prepared["scheduled_at"].time().replace(tzinfo=None)
                        if prepared["scheduled_at"]
                        else None
                    ),
                    appointment_remarks=prepared["appointment_remarks"],
                    appointment_status=prepared["appointment_status"],
                    raw_data=prepared["raw_data"],
                )
                item.full_clean()
                item.save()
                campaign_message = CampaignMessage(
                    organization=user.organization,
                    campaign_item=item,
                    template=template,
                    template_revision=template_revision,
                    rendered_content=format_message(template_content, item),
                )
                campaign_message.full_clean()
                campaign_message.save()

            refresh_campaign_summary(campaign)
            batch.status = ImportBatch.Status.IMPORTED
            batch.imported_count = len(prepared_rows)
            batch.processed_at = timezone.now()
            batch.save(
                update_fields=(
                    "status",
                    "imported_count",
                    "processed_at",
                    "updated_at",
                )
            )
            if replaces:
                replaces.status = ImportBatch.Status.REPLACED
                replaces.save(update_fields=("status", "updated_at"))
    except CsvImportError as exc:
        _mark_batch_failed(batch, exc)
        raise
    except Exception as exc:
        error = CsvImportError(
            "Unable to import the validated CSV rows.",
            errors=[{"message": str(exc)}],
        )
        _mark_batch_failed(batch, error)
        raise error from exc
    return campaign


def save_appointments_from_csv(user, file, list_title, messages):
    template = messages.first()
    if template is None:
        raise CsvImportError("Select a message template.")
    return save_campaign_from_csv(
        user=user,
        file=file,
        title=list_title,
        template=template,
        purpose=Campaign.Purpose.APPOINTMENT,
    )
