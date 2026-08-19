from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import TenantModel, validate_related_organizations


class Campaign(TenantModel):
    class Purpose(models.TextChoices):
        APPOINTMENT = "appointment", "Appointment reminders"
        MARKETING = "marketing", "Marketing"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=230)
    purpose = models.CharField(
        max_length=20, choices=Purpose.choices, default=Purpose.APPOINTMENT
    )
    import_batch = models.OneToOneField(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="campaign",
        blank=True,
        null=True,
    )
    template = models.ForeignKey(
        "messaging.MessageTemplate",
        on_delete=models.PROTECT,
        related_name="campaigns",
        blank=True,
        null=True,
    )
    template_revision = models.ForeignKey(
        "messaging.MessageTemplateRevision",
        on_delete=models.PROTECT,
        related_name="campaigns",
        blank=True,
        null=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="campaigns",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    summary = models.JSONField(default=dict, blank=True)
    scrub_after = models.DateTimeField(
        blank=True,
        null=True,
        help_text=(
            "When patient name and phone are removed from this list. "
            "Empty means they are kept indefinitely."
        ),
    )
    scrubbed_at = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        db_table = "rasel_campaign"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("organization", "purpose", "status"),
                name="campaign_org_status_idx",
            ),
            models.Index(
                fields=("organization", "created_at"),
                name="campaign_org_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=("appointment", "marketing")),
                name="valid_campaign_purpose",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=("draft", "ready", "active", "completed", "archived")
                ),
                name="valid_campaign_status",
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(
            self, "created_by", "template", "template_revision", "import_batch"
        )
        if (
            self.template_revision_id
            and self.template_revision.template_id != self.template_id
        ):
            raise ValidationError(
                {"template_revision": "Select a revision of the campaign template."}
            )
        if self.template_id and self.template.purpose not in {
            self.purpose,
            self.template.Purpose.GENERAL,
        }:
            raise ValidationError(
                {"template": "Select a template matching the campaign purpose."}
            )

    @property
    def is_scrubbed(self):
        return self.scrubbed_at is not None

    def __str__(self):
        return self.title


class CampaignItem(TenantModel):
    class AppointmentStatus(models.TextChoices):
        BOOKED = "booked", "Booked"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="items"
    )
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.PROTECT,
        related_name="campaign_items",
        blank=True,
        null=True,
    )
    contact = models.ForeignKey(
        "directory.Contact",
        on_delete=models.PROTECT,
        related_name="campaign_items",
    )
    doctor = models.ForeignKey(
        "directory.Doctor",
        on_delete=models.PROTECT,
        related_name="campaign_items",
        blank=True,
        null=True,
    )
    row_number = models.PositiveIntegerField(default=1)
    patient_name_snapshot = models.CharField(max_length=230)
    phone_number_snapshot = models.CharField(max_length=20)
    mrn_snapshot = models.CharField(max_length=230, blank=True)
    doctor_name_snapshot = models.CharField(max_length=230, blank=True)
    department_name_snapshot = models.CharField(max_length=150, blank=True)
    appointment_date = models.DateField(blank=True, null=True)
    appointment_time = models.TimeField(blank=True, null=True)
    appointment_remarks = models.CharField(max_length=500, blank=True)
    appointment_status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        blank=True,
        null=True,
    )
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rasel_campaignitem"
        ordering = ("row_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "row_number"), name="unique_campaign_row"
            ),
            models.CheckConstraint(
                condition=Q(appointment_status__isnull=True)
                | Q(
                    appointment_status__in=("booked", "confirmed", "cancelled")
                ),
                name="valid_campaign_appt_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "appointment_date"),
                name="item_org_date_idx",
            ),
            models.Index(
                fields=("organization", "appointment_status"),
                name="item_org_appt_status_idx",
            ),
            models.Index(
                fields=("organization", "doctor_name_snapshot"),
                name="item_org_doctor_idx",
            ),
            models.Index(
                fields=("organization", "phone_number_snapshot"),
                name="item_org_phone_idx",
            ),
            models.Index(
                fields=("organization", "mrn_snapshot"), name="item_org_mrn_idx"
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(
            self, "campaign", "appointment", "contact", "doctor"
        )
        if self.appointment_id:
            if self.appointment.contact_id != self.contact_id:
                raise ValidationError(
                    {"appointment": "Appointment and campaign item contacts must match."}
                )
            if self.appointment.doctor_id != self.doctor_id:
                raise ValidationError(
                    {"appointment": "Appointment and campaign item doctors must match."}
                )
        if self.campaign_id and self.campaign.purpose == Campaign.Purpose.APPOINTMENT:
            required = (
                self.appointment_date,
                self.appointment_time,
                self.appointment_status,
            )
            if not all(required):
                raise ValidationError(
                    "Appointment campaigns require date, time, and appointment status."
                )

    @property
    def doctor_name(self):
        return self.doctor_name_snapshot

    def __str__(self):
        return f"{self.patient_name_snapshot} - {self.campaign}"


class DoctorSummary(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPENED = "opened", "WhatsApp opened"
        SENT = "operator_marked_sent", "Operator marked sent"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="doctor_summaries"
    )
    doctor = models.ForeignKey(
        "directory.Doctor", on_delete=models.PROTECT, related_name="summaries"
    )
    rendered_content = models.TextField()
    metrics = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.DRAFT
    )
    opened_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_doctor_summaries",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "rasel_doctorsummary"
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "doctor"), name="unique_doctor_summary"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=("draft", "opened", "operator_marked_sent")
                ),
                name="valid_doctor_summary_status",
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "campaign", "doctor", "sent_by")

    def whatsapp_url(self):
        if not self.doctor.phone_number:
            return ""
        template = self.organization.whatsapp_url_template
        phone = "".join(
            character
            for character in self.doctor.phone_number
            if character.isdigit()
        )
        return template.format(
            phone=quote(phone, safe=""),
            message=quote(self.rendered_content, safe=""),
        )

    def __str__(self):
        return f"{self.campaign} - {self.doctor}"
