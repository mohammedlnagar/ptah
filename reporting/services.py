from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Q

from campaigns.models import CampaignItem, DoctorSummary
from messaging.models import CampaignMessage

from .messages import build_doctor_summary


@transaction.atomic
def refresh_campaign_summary(campaign):
    appointment_counts = {
        status: campaign.items.filter(appointment_status=status).count()
        for status in CampaignItem.AppointmentStatus.values
    }
    message_counts = {
        status: CampaignMessage.objects.filter(
            campaign_item__campaign=campaign,
            status=status,
        ).count()
        for status in CampaignMessage.Status.values
    }
    doctor_rows = list(
        campaign.items.filter(doctor__isnull=False)
        .values("doctor_id", "doctor__name", "doctor__department__name")
        .annotate(
            total=Count("id"),
            booked=Count(
                "id",
                filter=Q(appointment_status=CampaignItem.AppointmentStatus.BOOKED),
            ),
            confirmed=Count(
                "id",
                filter=Q(
                    appointment_status=CampaignItem.AppointmentStatus.CONFIRMED
                ),
            ),
            cancelled=Count(
                "id",
                filter=Q(
                    appointment_status=CampaignItem.AppointmentStatus.CANCELLED
                ),
            ),
        )
        .order_by("doctor__name", "doctor_id")
    )
    # Fetched once and grouped in memory rather than per doctor inside the
    # loop, which would be a query each.
    items_by_doctor = defaultdict(list)
    for item in campaign.items.filter(doctor__isnull=False).order_by(
        "appointment_date", "appointment_time", "row_number"
    ):
        items_by_doctor[item.doctor_id].append(item)

    active_doctor_ids = []
    doctor_metrics = {}
    for row in doctor_rows:
        active_doctor_ids.append(row["doctor_id"])
        metrics = {
            "total": row["total"],
            "booked": row["booked"],
            "confirmed": row["confirmed"],
            "cancelled": row["cancelled"],
        }
        doctor_name = row["doctor__name"]
        doctor_metrics[str(row["doctor_id"])] = {
            "name": doctor_name,
            "department": row["doctor__department__name"] or "",
            **metrics,
        }
        rendered_content = build_doctor_summary(
            campaign_title=campaign.title,
            doctor_name=doctor_name,
            department=row["doctor__department__name"] or "",
            items=items_by_doctor[row["doctor_id"]],
            metrics=metrics,
            # A scrubbed list has no names left to share.
            name_patients=not campaign.is_scrubbed,
        )
        DoctorSummary.objects.update_or_create(
            campaign=campaign,
            doctor_id=row["doctor_id"],
            defaults={
                "organization": campaign.organization,
                "rendered_content": rendered_content,
                "metrics": metrics,
            },
        )
    campaign.doctor_summaries.exclude(doctor_id__in=active_doctor_ids).delete()

    campaign.summary = {
        "total_items": campaign.items.count(),
        "appointments": appointment_counts,
        "messages": message_counts,
        "doctors": doctor_metrics,
    }
    campaign.save(update_fields=("summary", "updated_at"))
    return campaign.summary
