from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from campaigns.models import CampaignItem

from .models import Appointment, AppointmentStatusEvent


@transaction.atomic
def change_appointment_status(*, appointment, user, new_status, reason=""):
    appointment = Appointment.objects.select_for_update().get(pk=appointment.pk)
    if not user.organization_id or user.organization_id != appointment.organization_id:
        raise PermissionDenied("The appointment belongs to another organization.")
    if new_status not in Appointment.Status.values:
        raise ValidationError({"status": "Invalid appointment status."})
    if appointment.status == new_status:
        return appointment

    previous_status = appointment.status
    appointment.status = new_status
    appointment.full_clean()
    appointment.save(update_fields=("status", "updated_at"))
    CampaignItem.objects.filter(
        organization_id=appointment.organization_id,
        appointment=appointment,
    ).update(appointment_status=new_status)
    event = AppointmentStatusEvent(
        organization_id=appointment.organization_id,
        appointment=appointment,
        previous_status=previous_status,
        new_status=new_status,
        changed_by=user,
        reason=reason.strip(),
    )
    event.full_clean()
    event.save()
    from reporting.services import refresh_campaign_summary

    for campaign in {
        item.campaign
        for item in CampaignItem.objects.filter(
            organization_id=appointment.organization_id,
            appointment=appointment,
        ).select_related("campaign")
    }:
        refresh_campaign_summary(campaign)
    return appointment
