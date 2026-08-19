"""Retention scrubbing for campaign lists.

A finished list keeps being useful for reporting long after the patients on it
stop being anyone's business. These helpers strip the identifying columns out
of a list while leaving everything that makes it reportable, so a workspace can
hold a year of history without holding a year of patient names.
"""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from messaging.models import CampaignMessage

from .models import Campaign, CampaignItem


def row_fingerprint(raw_data):
    """A stable hash kept in place of the original CSV row.

    Enough to prove two imports carried the same row; not enough to read it
    back. ImportBatch.sha256 already covers the uploaded file as a whole.
    """
    payload = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def due_for_scrub(now=None):
    """Lists whose retention window has closed and that are not yet scrubbed."""
    return Campaign.objects.filter(
        scrub_after__isnull=False,
        scrub_after__lte=now or timezone.now(),
        scrubbed_at__isnull=True,
    )


@transaction.atomic
def scrub_campaign(campaign):
    """Strip patient identity from a list, keeping everything reportable.

    Name and phone are cleared and the raw CSV row is replaced by a hash of
    itself. The MRN, doctor, department, appointment date/time and status all
    survive, as do Campaign.summary and every DoctorSummary, so counts and
    per-doctor analysis still work afterwards.

    Contact and Appointment are deliberately untouched: they are the patient
    directory and the clinical record, not part of the campaign snapshot. That
    also means this is snapshot scrubbing rather than erasure — the row still
    points at a Contact that holds the name.

    bulk_update and queryset.update both bypass Model.save(), which matters:
    saving would re-run normalize_phone_number over the blanked phone and
    reject the empty string.
    """
    if campaign.scrubbed_at is not None:
        return 0

    items = list(
        CampaignItem.objects.filter(campaign=campaign).only("id", "raw_data")
    )
    for item in items:
        item.patient_name_snapshot = ""
        item.phone_number_snapshot = ""
        item.raw_data = (
            {"sha256": row_fingerprint(item.raw_data)} if item.raw_data else {}
        )
    if items:
        CampaignItem.objects.bulk_update(
            items,
            ["patient_name_snapshot", "phone_number_snapshot", "raw_data"],
            batch_size=500,
        )

    # The rendered WhatsApp text embeds the patient's name.
    CampaignMessage.objects.filter(campaign_item__campaign=campaign).update(
        rendered_content=""
    )

    now = timezone.now()
    Campaign.objects.filter(pk=campaign.pk).update(scrubbed_at=now, updated_at=now)
    campaign.scrubbed_at = now
    return len(items)
