"""The follow-up sequence: when each stage is due, and how it is generated.

Clinic policy, expressed once here so the queue, the import and the nightly
pass all agree:

* reminder      - two days before the appointment
* follow-up     - 24 hours before the appointment
* cancellation  - 19:00 local, the evening before, when no confirmation arrived

Nothing in here sends anything. A stage becoming due only means the message
starts appearing in the operator's queue; a person still opens every one in
WhatsApp.
"""

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction

from campaigns.models import CampaignItem
from messaging.formatting import format_message
from messaging.models import CampaignMessage


CANCELLATION_HOUR = 19

STAGE_TEMPLATE_FIELDS = {
    CampaignMessage.Stage.REMINDER: "template",
    CampaignMessage.Stage.FOLLOW_UP: "follow_up_template",
    CampaignMessage.Stage.CANCELLATION: "cancellation_template",
}


def organization_timezone(organization):
    """The clinic's timezone, falling back to UTC rather than raising.

    Import validates the timezone and refuses a bad one; this runs from the
    nightly pass too, where a misconfigured workspace should not stop every
    other workspace being processed.
    """
    try:
        return ZoneInfo(organization.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return datetime.timezone.utc


def appointment_datetime(item, tzinfo):
    """When the appointment is, as an aware datetime, or None.

    Prefers the Appointment record, which stores an aware timestamp. Falls
    back to the item's own snapshot columns, which are what survive if the
    appointment was never created (marketing campaigns have no appointment).
    """
    appointment = getattr(item, "appointment", None)
    if appointment is not None and appointment.scheduled_at:
        return appointment.scheduled_at
    if not item.appointment_date:
        return None
    time_part = item.appointment_time or datetime.time(0, 0)
    return datetime.datetime.combine(
        item.appointment_date, time_part, tzinfo=tzinfo
    )


def stage_due_at(stage, appointment_at, tzinfo):
    """When a stage becomes the operator's business, or None if it cannot."""
    if appointment_at is None:
        # No appointment to count back from: the message is due immediately,
        # which is how marketing reminders behave today.
        return None

    if stage == CampaignMessage.Stage.REMINDER:
        return appointment_at - datetime.timedelta(days=2)
    if stage == CampaignMessage.Stage.FOLLOW_UP:
        return appointment_at - datetime.timedelta(hours=24)
    if stage == CampaignMessage.Stage.CANCELLATION:
        # 19:00 on the day before, in the clinic's own timezone, so the
        # deadline lands at 19:00 locally whatever the server is set to.
        local = appointment_at.astimezone(tzinfo)
        evening_before = datetime.datetime.combine(
            local.date() - datetime.timedelta(days=1),
            datetime.time(CANCELLATION_HOUR, 0),
            tzinfo=tzinfo,
        )
        return evening_before
    return None


def stages_for(campaign):
    """The stages this campaign can actually produce, in sequence order.

    A stage exists only if the campaign has a template for it, so a marketing
    campaign with a reminder template alone keeps behaving exactly as before.
    """
    ordered = (
        CampaignMessage.Stage.REMINDER,
        CampaignMessage.Stage.FOLLOW_UP,
        CampaignMessage.Stage.CANCELLATION,
    )
    return [
        stage
        for stage in ordered
        if getattr(campaign, STAGE_TEMPLATE_FIELDS[stage] + "_id", None)
    ]


def _template_for(campaign, stage):
    return getattr(campaign, STAGE_TEMPLATE_FIELDS[stage])


@transaction.atomic
def generate_stage_messages(campaign, items=None):
    """Create any missing stage messages for the given items.

    Idempotent: a message that already exists for a stage is left alone, so
    this is safe to call again after a campaign update adds rows. Returns how
    many messages were created.
    """
    stages = stages_for(campaign)
    if not stages:
        return 0

    tzinfo = organization_timezone(campaign.organization)
    if items is None:
        items = CampaignItem.objects.filter(campaign=campaign).select_related(
            "appointment"
        )

    existing = set(
        CampaignMessage.objects.filter(campaign_item__campaign=campaign).values_list(
            "campaign_item_id", "stage"
        )
    )

    created = []
    for item in items:
        appointment_at = appointment_datetime(item, tzinfo)
        for stage in stages:
            if (item.pk, stage) in existing:
                continue
            template = _template_for(campaign, stage)
            revision = template.current_revision
            content = revision.content if revision else template.content
            created.append(
                CampaignMessage(
                    organization=campaign.organization,
                    campaign_item=item,
                    stage=stage,
                    template=template,
                    template_revision=revision,
                    rendered_content=format_message(content, item),
                    due_at=stage_due_at(stage, appointment_at, tzinfo),
                )
            )

    if created:
        CampaignMessage.objects.bulk_create(created)
    return len(created)


@transaction.atomic
def void_settled_cancellations(campaign=None, now=None):
    """Retire cancellation messages that events have overtaken.

    A cancellation is only meaningful while the appointment is unconfirmed. If
    the patient confirmed before 19:00, the message is voided rather than
    skipped: skipping is a decision an operator made, and recording this as a
    skip would misattribute it.

    What is left behind — a pending cancellation that is due — is precisely the
    list of appointments needing a human decision, which is the flag the policy
    asks for. Nothing is cancelled automatically.
    """
    from django.utils import timezone as dj_timezone

    now = now or dj_timezone.now()
    due = CampaignMessage.objects.filter(
        stage=CampaignMessage.Stage.CANCELLATION,
        status=CampaignMessage.Status.PENDING,
        due_at__lte=now,
        campaign_item__appointment_status=CampaignItem.AppointmentStatus.CONFIRMED,
    )
    if campaign is not None:
        due = due.filter(campaign_item__campaign=campaign)
    return due.update(status=CampaignMessage.Status.VOIDED)
