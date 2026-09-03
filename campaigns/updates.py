"""Applying an updated export to a campaign that already exists.

The clinic re-exports the same clinic day after patients have replied. That
file is not a new campaign: most rows are appointments already in the queue
whose status has moved, some are genuinely new bookings, and the rest are
unchanged. This applies it in place so the follow-up stages act on current
status rather than on what was true at first import.

Matching is deliberately narrow. A row is matched on the patient (MRN, or
phone number when the patient has no MRN yet), the appointment date and time,
and the clinician. Anything that does not match all three is treated as a new
appointment rather than guessed at, because attaching one patient's update to
another patient's record is far worse than importing a duplicate row somebody
can see and delete.
"""

import datetime
import hashlib

from django.db import transaction
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatusEvent
from campaigns.followups import (
    appointment_datetime,
    generate_stage_messages,
    organization_timezone,
)
from campaigns.models import Campaign, CampaignItem
from directory.services import resolve_contact, resolve_department, resolve_doctor
from imports.models import ImportBatch
from rasel.utilities.csv_handler import (
    CsvImportError,
    clean_csv_data,
    prepare_csv_rows,
)
from reporting.services import refresh_campaign_summary


def _canonical(value):
    return (value or "").strip().casefold()


def match_key(*, mrn, phone, scheduled_at, doctor_name):
    """The identity a row and an existing item are compared on.

    MRN identifies the patient when there is one; phone stands in for patients
    the clinic has not issued an MRN to yet. The appointment time and clinician
    complete the key, so the same patient can hold several appointments in one
    campaign without them colliding.
    """
    patient = _canonical(mrn) or ("phone:" + _canonical(phone))
    # Normalised to UTC before formatting: the database hands back an aware
    # UTC value while the CSV is parsed in the clinic's timezone, and the same
    # instant in two offsets does not compare equal as text.
    when = (
        scheduled_at.astimezone(datetime.timezone.utc).isoformat()
        if scheduled_at
        else ""
    )
    return (patient, when, _canonical(doctor_name))


def _item_key(item, tzinfo):
    return match_key(
        mrn=item.mrn_snapshot,
        phone=item.phone_number_snapshot,
        scheduled_at=appointment_datetime(item, tzinfo),
        doctor_name=item.doctor_name_snapshot,
    )


@transaction.atomic
def update_campaign_from_csv(*, user, campaign, file):
    """Apply an updated export to `campaign`.

    Returns a summary of what changed: how many rows matched, how many changed
    status, how many were added, and how many rows could not be matched and so
    became new appointments.
    """
    organization = user.organization
    if campaign.organization_id != organization.id:
        raise CsvImportError("That campaign belongs to another organization.")
    if campaign.scrubbed_at is not None:
        # The snapshot this would match against has been deliberately removed.
        raise CsvImportError(
            "This list has been scrubbed for retention, so it can no longer be updated."
        )

    payload = file.read()
    file.seek(0)

    batch = ImportBatch(
        organization=organization,
        uploaded_by=user,
        purpose=campaign.purpose,
        original_filename=getattr(file, "name", "update.csv")[:255],
        sha256=hashlib.sha256(payload).hexdigest(),
        status=ImportBatch.Status.UPLOADED,
        updates_campaign=campaign,
    )
    batch.full_clean()
    batch.save()

    # prepare_csv_rows raises on the first invalid row rather than returning
    # partial results, so an update is all-or-nothing like an import. The
    # failed batch is still recorded, so the operator can see what was
    # rejected and why.
    try:
        frame = clean_csv_data(file, campaign.purpose)
        prepared_rows = prepare_csv_rows(frame, campaign.purpose, organization)
    except CsvImportError as error:
        batch.status = ImportBatch.Status.FAILED
        batch.error_count = max(len(error.errors), 1)
        batch.errors = error.errors
        batch.processed_at = timezone.now()
        batch.save(
            update_fields=[
                "status",
                "error_count",
                "errors",
                "processed_at",
                "updated_at",
            ]
        )
        raise

    batch.row_count = len(prepared_rows)
    batch.save(update_fields=["row_count", "updated_at"])

    tzinfo = organization_timezone(organization)
    existing = {
        _item_key(item, tzinfo): item
        for item in CampaignItem.objects.filter(campaign=campaign).select_related(
            "appointment"
        )
    }

    matched = 0
    status_changed = 0
    added = 0
    next_row_number = (
        CampaignItem.objects.filter(campaign=campaign)
        .order_by("-row_number")
        .values_list("row_number", flat=True)
        .first()
        or 0
    )
    new_items = []

    for prepared in prepared_rows:
        key = match_key(
            mrn=prepared["mrn"],
            phone=prepared["phone"],
            scheduled_at=prepared["scheduled_at"],
            doctor_name=prepared["doctor_name"],
        )
        item = existing.get(key)

        if item is not None:
            matched += 1
            new_status = prepared["appointment_status"]
            if new_status and new_status != item.appointment_status:
                _apply_status(item, new_status, user)
                status_changed += 1
            # Remarks are the clinic's own note and can change between
            # exports; the rest of the snapshot is identity and stays put.
            if prepared["appointment_remarks"] != item.appointment_remarks:
                item.appointment_remarks = prepared["appointment_remarks"]
                item.save(update_fields=["appointment_remarks", "updated_at"])
            continue

        next_row_number += 1
        new_items.append(
            _create_item(
                organization=organization,
                user=user,
                campaign=campaign,
                batch=batch,
                prepared=prepared,
                row_number=next_row_number,
            )
        )
        added += 1

    # One idempotent pass covers both the rows just added and any existing row
    # missing a later stage, which happens when a campaign gains a stage
    # template after its first import.
    created_messages = generate_stage_messages(campaign)

    batch.status = ImportBatch.Status.IMPORTED
    batch.imported_count = added
    batch.processed_at = timezone.now()
    batch.save(
        update_fields=["status", "imported_count", "processed_at", "updated_at"]
    )

    refresh_campaign_summary(campaign)
    return {
        "batch": batch,
        "matched": matched,
        "status_changed": status_changed,
        "added": added,
        "messages_created": created_messages,
    }


def _apply_status(item, new_status, user):
    """Record the status move on the item and, where present, the appointment."""
    previous = item.appointment_status
    item.appointment_status = new_status
    item.save(update_fields=["appointment_status", "updated_at"])

    appointment = getattr(item, "appointment", None)
    if appointment is None:
        return
    appointment.status = new_status
    appointment.save(update_fields=["status", "updated_at"])
    event = AppointmentStatusEvent(
        organization=item.organization,
        appointment=appointment,
        previous_status=previous,
        new_status=new_status,
        changed_by=user,
        reason="Updated from a re-uploaded export.",
    )
    event.full_clean()
    event.save()


def _create_item(*, organization, user, campaign, batch, prepared, row_number):
    contact = resolve_contact(
        organization=organization,
        name=prepared["patient_name"],
        phone_number=prepared["phone"],
        mrn=prepared["mrn"],
    )

    doctor = None
    appointment = None
    if campaign.purpose == Campaign.Purpose.APPOINTMENT:
        department = None
        if prepared["department_name"]:
            department = resolve_department(
                organization=organization, name=prepared["department_name"]
            )
        if prepared["doctor_name"]:
            doctor = resolve_doctor(
                organization=organization,
                name=prepared["doctor_name"],
                department=department,
            )
        appointment = Appointment(
            organization=organization,
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
        event = AppointmentStatusEvent(
            organization=organization,
            appointment=appointment,
            previous_status="",
            new_status=appointment.status,
            changed_by=user,
            reason="Added by a campaign update.",
        )
        event.full_clean()
        event.save()

    item = CampaignItem(
        organization=organization,
        campaign=campaign,
        appointment=appointment,
        contact=contact,
        doctor=doctor,
        row_number=row_number,
        patient_name_snapshot=prepared["patient_name"],
        phone_number_snapshot=prepared["phone"],
        mrn_snapshot=prepared["mrn"],
        doctor_name_snapshot=prepared["doctor_name"],
        department_name_snapshot=prepared["department_name"],
        appointment_date=(
            prepared["scheduled_at"].date() if prepared["scheduled_at"] else None
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
    return item
