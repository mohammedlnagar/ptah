from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from account.models import Organization, TimeStampedModel


def validate_related_organizations(instance, *field_names):
    errors = {}
    for field_name in field_names:
        if not getattr(instance, f"{field_name}_id", None):
            continue
        related = getattr(instance, field_name)
        if related.organization_id != instance.organization_id:
            errors[field_name] = "Related records must share an organization."
    if errors:
        raise ValidationError(errors)


class TenantQuerySet(models.QuerySet):
    def for_organization(self, organization):
        return self.filter(organization=organization)

    def for_user(self, user):
        if user.is_superuser and user.organization_id is None:
            return self
        return self.for_organization(user.organization)


class TenantModel(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class Department(TenantModel):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"), name="unique_department_name_per_org"
            ),
            models.UniqueConstraint(
                fields=("organization", "code"),
                condition=~Q(code=""),
                name="unique_department_code_per_org",
            ),
        ]

    def __str__(self):
        return self.name


class Doctor(TenantModel):
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="doctors", blank=True, null=True
    )
    name = models.CharField(max_length=230)
    code = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "code"),
                condition=~Q(code=""),
                name="unique_doctor_code_per_org",
            )
        ]
        indexes = [models.Index(fields=("organization", "name"), name="doctor_org_name_idx")]

    def clean(self):
        super().clean()
        if self.department_id and self.department.organization_id != self.organization_id:
            raise ValidationError({"department": "Doctor and department must share an organization."})

    def __str__(self):
        return self.name


class Contact(TenantModel):
    name = models.CharField(max_length=230)
    phone_number = models.CharField(max_length=20)
    mrn = models.CharField(max_length=230, blank=True, null=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "phone_number"), name="unique_contact_phone_per_org"
            ),
            models.UniqueConstraint(
                fields=("organization", "mrn"),
                condition=Q(mrn__isnull=False) & ~Q(mrn=""),
                name="unique_contact_mrn_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "name"), name="contact_org_name_idx"),
            models.Index(fields=("organization", "mrn"), name="contact_org_mrn_idx"),
        ]

    def __str__(self):
        return f"{self.name} - {self.phone_number}"


class MessageTemplate(TenantModel):
    class Purpose(models.TextChoices):
        APPOINTMENT = "appointment", "Appointment reminder"
        MARKETING = "marketing", "Marketing"
        GENERAL = "general", "General"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_message_templates"
    )
    name = models.CharField(max_length=255)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.APPOINTMENT)
    content = models.TextField()
    approval_status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_message_templates",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        permissions = [("approve_messagetemplate", "Can approve message templates")]
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"), name="unique_template_name_per_org"
            )
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "created_by", "approved_by")

    def __str__(self):
        return self.name


class ImportBatch(TenantModel):
    class Purpose(models.TextChoices):
        APPOINTMENT = "appointment", "Appointment reminders"
        MARKETING = "marketing", "Marketing"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        VALIDATED = "validated", "Validated"
        IMPORTED = "imported", "Imported"
        FAILED = "failed", "Failed"
        REPLACED = "replaced", "Replaced"

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="imports"
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    original_filename = models.CharField(max_length=255)
    source_file = models.FileField(upload_to="imports/%Y/%m/", blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    replaces = models.OneToOneField(
        "self", on_delete=models.SET_NULL, related_name="replacement", blank=True, null=True
    )
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "purpose", "status"), name="import_org_purpose_idx")
        ]

    def clean(self):
        super().clean()
        if self.uploaded_by_id and self.uploaded_by.organization_id != self.organization_id:
            raise ValidationError({"uploaded_by": "Uploader and import must share an organization."})
        if self.replaces_id:
            if self.replaces.organization_id != self.organization_id:
                raise ValidationError({"replaces": "Replacement uploads must share an organization."})
            if self.replaces.status != self.Status.FAILED:
                raise ValidationError({"replaces": "Only a failed import can be replaced."})

    def __str__(self):
        return self.original_filename


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
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.APPOINTMENT)
    import_batch = models.OneToOneField(
        ImportBatch, on_delete=models.PROTECT, related_name="campaign", blank=True, null=True
    )
    template = models.ForeignKey(
        MessageTemplate, on_delete=models.PROTECT, related_name="campaigns", blank=True, null=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="campaigns"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "purpose", "status"), name="campaign_org_status_idx"),
            models.Index(fields=("organization", "created_at"), name="campaign_org_created_idx"),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "created_by", "template", "import_batch")

    def __str__(self):
        return self.title


class CampaignItem(TenantModel):
    class AppointmentStatus(models.TextChoices):
        BOOKED = "booked", "Booked"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="items")
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="campaign_items")
    doctor = models.ForeignKey(
        Doctor, on_delete=models.PROTECT, related_name="campaign_items", blank=True, null=True
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
        max_length=20, choices=AppointmentStatus.choices, blank=True, null=True
    )
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("row_number", "id")
        constraints = [
            models.UniqueConstraint(fields=("campaign", "row_number"), name="unique_campaign_row")
        ]
        indexes = [
            models.Index(fields=("organization", "appointment_date"), name="item_org_date_idx"),
            models.Index(fields=("organization", "appointment_status"), name="item_org_appt_status_idx"),
            models.Index(fields=("organization", "doctor_name_snapshot"), name="item_org_doctor_idx"),
            models.Index(fields=("organization", "phone_number_snapshot"), name="item_org_phone_idx"),
            models.Index(fields=("organization", "mrn_snapshot"), name="item_org_mrn_idx"),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "campaign", "contact", "doctor")
        if self.campaign_id and self.campaign.purpose == Campaign.Purpose.APPOINTMENT:
            required = (self.appointment_date, self.appointment_time, self.appointment_status)
            if not all(required):
                raise ValidationError("Appointment campaigns require date, time, and appointment status.")

    @property
    def doctor_name(self):
        return self.doctor_name_snapshot

    def __str__(self):
        return f"{self.patient_name_snapshot} - {self.campaign}"


class CampaignMessage(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        OPENED = "opened", "WhatsApp opened"
        SENT = "sent", "Marked sent"
        SKIPPED = "skipped", "Skipped"

    campaign_item = models.OneToOneField(
        CampaignItem, on_delete=models.CASCADE, related_name="message"
    )
    template = models.ForeignKey(
        MessageTemplate, on_delete=models.SET_NULL, related_name="rendered_messages", blank=True, null=True
    )
    rendered_content = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    opened_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_campaign_messages",
        blank=True,
        null=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=("organization", "status"), name="message_org_status_idx")
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "campaign_item", "template", "sent_by")

    def whatsapp_url(self):
        template = self.organization.whatsapp_url_template
        phone = "".join(character for character in self.campaign_item.phone_number_snapshot if character.isdigit())
        return template.format(
            phone=quote(phone),
            message=quote(self.rendered_content),
        )

    def __str__(self):
        return f"Message for {self.campaign_item.patient_name_snapshot}"


class DoctorSummary(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPENED = "opened", "WhatsApp opened"
        SENT = "sent", "Marked sent"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="doctor_summaries")
    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="summaries")
    rendered_content = models.TextField()
    metrics = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
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
        constraints = [
            models.UniqueConstraint(fields=("campaign", "doctor"), name="unique_doctor_summary")
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "campaign", "doctor", "sent_by")

    def __str__(self):
        return f"{self.campaign} - {self.doctor}"
