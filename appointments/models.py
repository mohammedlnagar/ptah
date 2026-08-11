from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import TenantModel, validate_related_organizations


class Appointment(TenantModel):
    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    contact = models.ForeignKey(
        "directory.Contact", on_delete=models.PROTECT, related_name="appointments"
    )
    doctor = models.ForeignKey(
        "directory.Doctor",
        on_delete=models.PROTECT,
        related_name="appointments",
        blank=True,
        null=True,
    )
    source_import = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="appointments",
        blank=True,
        null=True,
    )
    external_reference = models.CharField(max_length=255, blank=True)
    scheduled_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOOKED
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ("scheduled_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "external_reference"),
                condition=~Q(external_reference=""),
                name="unique_appt_ref_per_org",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("booked", "confirmed", "cancelled")),
                name="valid_appointment_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "scheduled_at"),
                name="appt_org_scheduled_idx",
            ),
            models.Index(
                fields=("organization", "status"), name="appt_org_status_idx"
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "contact", "doctor", "source_import")
        if self.source_import_id and self.source_import.purpose != "appointment":
            raise ValidationError(
                {"source_import": "Appointments require an appointment import."}
            )

    def __str__(self):
        return f"{self.contact} - {self.scheduled_at:%Y-%m-%d %H:%M}"


class AppointmentStatusEvent(TenantModel):
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="status_events"
    )
    previous_status = models.CharField(
        max_length=20, choices=Appointment.Status.choices, blank=True
    )
    new_status = models.CharField(max_length=20, choices=Appointment.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointment_status_events",
    )
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("organization", "created_at"), name="appt_event_org_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(previous_status="")
                | Q(previous_status__in=Appointment.Status.values),
                name="valid_previous_appt_status",
            ),
            models.CheckConstraint(
                condition=Q(new_status__in=Appointment.Status.values),
                name="valid_new_appt_status",
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "appointment", "changed_by")
        if self.previous_status and self.previous_status == self.new_status:
            raise ValidationError(
                {"new_status": "The new status must differ from the previous status."}
            )

    def __str__(self):
        return f"{self.appointment} -> {self.get_new_status_display()}"
