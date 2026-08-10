from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SubscriptionPlan(TimeStampedModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50, unique=True)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_users = models.PositiveIntegerField(default=5)
    max_monthly_campaigns = models.PositiveIntegerField(default=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("monthly_price", "name")

    def __str__(self):
        return self.name


class Organization(TimeStampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    timezone = models.CharField(max_length=64, default="Asia/Dubai")
    whatsapp_url_template = models.CharField(
        max_length=500,
        default="https://wa.me/{phone}?text={message}",
        help_text="Must contain the {phone} and {message} placeholders.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def clean(self):
        super().clean()
        required = {"{phone}", "{message}"}
        missing = {placeholder for placeholder in required if placeholder not in self.whatsapp_url_template}
        if missing:
            raise ValidationError(
                {"whatsapp_url_template": f"Missing placeholders: {', '.join(sorted(missing))}"}
            )

    def __str__(self):
        return self.name


class OrganizationSubscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    starts_on = models.DateField()
    ends_on = models.DateField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=("status", "ends_on"), name="subscription_status_idx")]

    def clean(self):
        super().clean()
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": "The end date cannot precede the start date."})

    def __str__(self):
        return f"{self.organization} - {self.plan}"


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="employees",
        blank=True,
        null=True,
        help_text="Required for tenant employees; platform superusers may be unassigned.",
    )
    groups = models.ManyToManyField(
        "auth.Group", related_name="custom_user_groups", blank=True
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission", related_name="custom_user_permissions", blank=True
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(organization__isnull=False) | Q(is_superuser=True),
                name="employee_requires_organization",
            )
        ]
        indexes = [models.Index(fields=("organization", "is_active"), name="user_org_active_idx")]

    def __str__(self):
        return self.email


class UserProfile(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="profile"
    )
    passport = models.ImageField(upload_to="documents/", blank=True, null=True)
    emirates_id = models.ImageField(upload_to="documents/", blank=True, null=True)
    university_certificate = models.FileField(upload_to="documents/", blank=True, null=True)
    cv = models.FileField(upload_to="documents/", blank=True, null=True)
    legacy_role = models.CharField(
        max_length=100,
        blank=True,
        help_text="Historical value only. Authorization is managed with Django groups.",
    )
    work_email = models.EmailField(blank=True, null=True)
    home_address = models.TextField(blank=True, null=True)
    marital_status = models.CharField(
        max_length=20,
        choices=[("Single", "Single"), ("Married", "Married")],
        blank=True,
        null=True,
    )
    visa_copy = models.FileField(upload_to="documents/", blank=True, null=True)
    birthdate = models.DateField(blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)

    def get_documents(self):
        return {
            self.passport: "Passport",
            self.emirates_id: "Emirates ID",
            self.university_certificate: "University Certificate",
            self.cv: "CV",
            self.visa_copy: "Visa Copy",
        }

    def __str__(self):
        return f"Profile of {self.user.email}"


@receiver(post_save, sender=CustomUser)
def ensure_user_profile(sender, instance, **kwargs):
    UserProfile.objects.get_or_create(user=instance)
