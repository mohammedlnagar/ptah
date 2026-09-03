from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from common.models import TenantModel, validate_related_organizations


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
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="imports",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    original_filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED
    )
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    # Set when this upload updates an existing campaign rather than creating
    # one. Named for the direction it points because Campaign.import_batch
    # already claims the reverse accessor `campaign` for the original upload.
    updates_campaign = models.ForeignKey(
        "campaigns.Campaign",
        on_delete=models.CASCADE,
        related_name="update_batches",
        blank=True,
        null=True,
    )
    replaces = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        related_name="replacement",
        blank=True,
        null=True,
    )
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "rasel_importbatch"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("organization", "purpose", "status"),
                name="import_org_purpose_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=("appointment", "marketing")),
                name="valid_import_purpose",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "uploaded",
                        "validated",
                        "imported",
                        "failed",
                        "replaced",
                    )
                ),
                name="valid_import_status",
            ),
            models.CheckConstraint(
                condition=Q(imported_count__lte=F("row_count")),
                name="imported_not_above_rows",
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "uploaded_by", "replaces")
        if self.replaces_id and self.replaces.status != self.Status.FAILED:
            raise ValidationError(
                {"replaces": "Only a failed import can be replaced."}
            )

    def __str__(self):
        return self.original_filename


class ImportIssue(TenantModel):
    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="issues",
    )
    row_number = models.PositiveIntegerField(blank=True, null=True)
    column = models.CharField(max_length=255, blank=True)
    code = models.CharField(max_length=50, blank=True)
    message = models.CharField(max_length=1000)

    class Meta:
        ordering = ("row_number", "id")
        indexes = [
            models.Index(
                fields=("organization", "batch", "row_number"),
                name="import_issue_lookup_idx",
            )
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "batch")

    def __str__(self):
        location = f"row {self.row_number}" if self.row_number else "file"
        return f"{self.batch}: {location} - {self.message}"
