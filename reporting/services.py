from django.db import transaction
from django.db.models import Count, Q

from campaigns.models import CampaignItem, DoctorSummary
from messaging.models import CampaignMessage


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
        rendered_content = (
            f"{doctor_name} appointment summary for {campaign.title}: "
            f"{metrics['total']} total, {metrics['booked']} booked, "
            f"{metrics['confirmed']} confirmed, and "
            f"{metrics['cancelled']} cancelled."
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
