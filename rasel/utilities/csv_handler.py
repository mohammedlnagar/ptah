import hashlib
from collections import Counter

import pandas as pd
from django.db import transaction
from django.utils import timezone

from ..models import (
    Campaign,
    CampaignItem,
    CampaignMessage,
    Contact,
    Department,
    Doctor,
    ImportBatch,
)
from .message_formatter import format_message


COMMON_REQUIRED_COLUMNS = {"Patient Name", "Patient Mobile"}
APPOINTMENT_REQUIRED_COLUMNS = {
    "Appointment Date",
    "Appointment Date/Time",
    "Consultant",
}


class CsvImportError(ValueError):
    pass


def _json_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _normalize_phone(value):
    phone = str(value).strip().replace(" ", "").replace("-", "")
    if phone.endswith(".0"):
        phone = phone[:-2]
    if not phone:
        raise CsvImportError("A row contains an empty patient mobile number.")
    return phone


def _clean_optional(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_appointment_status(value):
    status = str(value or "").strip().lower()
    if status in {"confirmed"}:
        return CampaignItem.AppointmentStatus.CONFIRMED
    if status in {"cancelled", "canceled"}:
        return CampaignItem.AppointmentStatus.CANCELLED
    return CampaignItem.AppointmentStatus.BOOKED


def clean_csv_data(file, purpose):
    try:
        file.seek(0)
        frame = pd.read_csv(file, dtype=str)
    except Exception as exc:
        raise CsvImportError(f"Unable to read CSV file: {exc}") from exc

    frame.columns = [str(column).strip() for column in frame.columns]
    required = set(COMMON_REQUIRED_COLUMNS)
    if purpose == Campaign.Purpose.APPOINTMENT:
        required.update(APPOINTMENT_REQUIRED_COLUMNS)
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise CsvImportError(f"Missing columns: {', '.join(missing)}")

    frame = frame.dropna(how="all").reset_index(drop=True)
    if frame.empty:
        raise CsvImportError("The CSV contains no data rows.")

    if purpose == Campaign.Purpose.APPOINTMENT:
        frame["Appointment Date/Time"] = pd.to_datetime(
            frame["Appointment Date/Time"], dayfirst=True, errors="coerce"
        )
        if frame["Appointment Date/Time"].isna().any():
            rows = [str(index + 2) for index in frame.index[frame["Appointment Date/Time"].isna()]]
            raise CsvImportError(f"Invalid appointment date/time on rows: {', '.join(rows)}")
    return frame


@transaction.atomic
def save_campaign_from_csv(user, file, title, template, purpose, replaces=None):
    if not user.organization_id:
        raise CsvImportError("The user must belong to an organization.")
    if template.organization_id != user.organization_id:
        raise CsvImportError("The selected template belongs to another organization.")
    if replaces and (
        replaces.organization_id != user.organization_id
        or replaces.status != ImportBatch.Status.FAILED
    ):
        raise CsvImportError("Only a failed import from this organization can be replaced.")

    file.seek(0)
    digest = hashlib.sha256(file.read()).hexdigest()
    file.seek(0)
    batch = ImportBatch.objects.create(
        organization=user.organization,
        uploaded_by=user,
        purpose=purpose,
        original_filename=file.name,
        source_file=file,
        sha256=digest,
        replaces=replaces,
    )

    try:
        frame = clean_csv_data(file, purpose)
    except CsvImportError as exc:
        batch.status = ImportBatch.Status.FAILED
        batch.error_count = 1
        batch.errors = [{"message": str(exc)}]
        batch.processed_at = timezone.now()
        batch.save(update_fields=("status", "error_count", "errors", "processed_at", "updated_at"))
        raise

    campaign = Campaign.objects.create(
        organization=user.organization,
        title=title,
        purpose=purpose,
        import_batch=batch,
        template=template,
        created_by=user,
        status=Campaign.Status.READY,
    )

    status_counts = Counter()
    doctor_counts = Counter()
    for row_offset, (_, row) in enumerate(frame.iterrows(), start=1):
        phone = _normalize_phone(row["Patient Mobile"])
        patient_name = _clean_optional(row["Patient Name"])
        mrn = _clean_optional(row.get("MR No."))

        contact, _ = Contact.objects.get_or_create(
            organization=user.organization,
            phone_number=phone,
            defaults={"name": patient_name, "mrn": mrn or None},
        )
        changed = False
        if contact.name != patient_name:
            contact.name = patient_name
            changed = True
        if mrn and not contact.mrn:
            contact.mrn = mrn
            changed = True
        if changed:
            contact.save(update_fields=("name", "mrn", "updated_at"))

        doctor = None
        doctor_name = ""
        department_name = ""
        appointment_date = None
        appointment_time = None
        appointment_status = None
        if purpose == Campaign.Purpose.APPOINTMENT:
            doctor_name = _clean_optional(row.get("Consultant"))
            department_name = _clean_optional(row.get("Doctor Department"))
            department = None
            if department_name:
                department, _ = Department.objects.get_or_create(
                    organization=user.organization, name=department_name
                )
            if doctor_name:
                doctor, _ = Doctor.objects.get_or_create(
                    organization=user.organization,
                    name=doctor_name,
                    defaults={"department": department},
                )
            appointment_datetime = row["Appointment Date/Time"]
            appointment_date = appointment_datetime.date()
            appointment_time = appointment_datetime.time()
            appointment_status = _normalize_appointment_status(row.get("Appointment Status"))
            status_counts[appointment_status] += 1
            doctor_counts[doctor_name or "Unassigned"] += 1

        item = CampaignItem.objects.create(
            organization=user.organization,
            campaign=campaign,
            contact=contact,
            doctor=doctor,
            row_number=row_offset,
            patient_name_snapshot=patient_name,
            phone_number_snapshot=phone,
            mrn_snapshot=mrn,
            doctor_name_snapshot=doctor_name,
            department_name_snapshot=department_name,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            appointment_remarks=_clean_optional(row.get("Remarks")),
            appointment_status=appointment_status,
            raw_data={str(key): _json_value(value) for key, value in row.items()},
        )
        CampaignMessage.objects.create(
            organization=user.organization,
            campaign_item=item,
            template=template,
            rendered_content=format_message(template.content, item),
        )

    campaign.summary = {
        "total_items": len(frame),
        "appointment_statuses": dict(status_counts),
        "doctors": dict(doctor_counts),
    }
    campaign.save(update_fields=("summary", "updated_at"))
    batch.status = ImportBatch.Status.IMPORTED
    batch.row_count = len(frame)
    batch.imported_count = len(frame)
    batch.processed_at = timezone.now()
    batch.save(
        update_fields=(
            "status",
            "row_count",
            "imported_count",
            "processed_at",
            "updated_at",
        )
    )
    if replaces:
        replaces.status = ImportBatch.Status.REPLACED
        replaces.save(update_fields=("status", "updated_at"))
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
