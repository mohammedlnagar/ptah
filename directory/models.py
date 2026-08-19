from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import TenantModel

from .normalization import canonical_key, clean_display_text, normalize_phone_number


class Department(TenantModel):
    name = models.CharField(max_length=150)
    normalized_name = models.CharField(max_length=150, default="", editable=False)
    code = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "rasel_department"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "normalized_name"),
                name="unique_department_name_per_org",
            ),
            models.UniqueConstraint(
                fields=("organization", "code"),
                condition=~Q(code=""),
                name="unique_department_code_per_org",
            ),
        ]

    def clean(self):
        super().clean()
        self.name = clean_display_text(self.name)
        self.normalized_name = canonical_key(self.name)

    def save(self, *args, **kwargs):
        self.name = clean_display_text(self.name)
        self.normalized_name = canonical_key(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Doctor(TenantModel):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="doctors",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=230)
    normalized_name = models.CharField(max_length=230, default="", editable=False)
    code = models.CharField(max_length=100, blank=True)
    normalized_code = models.CharField(max_length=100, blank=True, editable=False)
    phone_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "rasel_doctor"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "normalized_code"),
                condition=~Q(normalized_code=""),
                name="unique_doctor_code_per_org",
            )
        ]
        indexes = [
            models.Index(
                fields=("organization", "normalized_name", "department"),
                name="doctor_org_name_idx",
            )
        ]

    def clean(self):
        super().clean()
        self.name = clean_display_text(self.name)
        self.normalized_name = canonical_key(self.name)
        self.code = clean_display_text(self.code)
        self.normalized_code = canonical_key(self.code)
        if self.phone_number:
            self.phone_number = normalize_phone_number(self.phone_number)
        if (
            self.department_id
            and self.department.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"department": "Doctor and department must share an organization."}
            )

    def save(self, *args, **kwargs):
        self.name = clean_display_text(self.name)
        self.normalized_name = canonical_key(self.name)
        self.code = clean_display_text(self.code)
        self.normalized_code = canonical_key(self.code)
        if self.phone_number:
            self.phone_number = normalize_phone_number(self.phone_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Contact(TenantModel):
    name = models.CharField(max_length=230)
    phone_number = models.CharField(max_length=20)
    mrn = models.CharField(max_length=230, blank=True, null=True)
    normalized_mrn = models.CharField(
        max_length=230, blank=True, default="", editable=False
    )

    class Meta:
        db_table = "rasel_contact"
        ordering = ("name",)
        constraints = [
            # Families share a mobile, so a phone number may repeat as long as
            # each patient carries their own MRN. Only one MRN-less patient may
            # hold a given number, so rows without an MRN still de-duplicate
            # instead of piling up on every re-import.
            models.UniqueConstraint(
                fields=("organization", "phone_number"),
                condition=Q(normalized_mrn=""),
                name="unique_contact_phone_without_mrn_per_org",
            ),
            models.UniqueConstraint(
                fields=("organization", "normalized_mrn"),
                condition=~Q(normalized_mrn=""),
                name="unique_contact_mrn_per_org",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "name"), name="contact_org_name_idx"
            ),
            models.Index(
                fields=("organization", "normalized_mrn"),
                name="contact_org_mrn_idx",
            ),
        ]

    def clean(self):
        super().clean()
        self.name = clean_display_text(self.name)
        self.phone_number = normalize_phone_number(self.phone_number)
        self.mrn = clean_display_text(self.mrn) or None
        self.normalized_mrn = canonical_key(self.mrn)

    def save(self, *args, **kwargs):
        self.name = clean_display_text(self.name)
        self.phone_number = normalize_phone_number(self.phone_number)
        self.mrn = clean_display_text(self.mrn) or None
        self.normalized_mrn = canonical_key(self.mrn)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.phone_number}"
