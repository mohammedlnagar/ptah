import datetime
import secrets

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from common.models import TimeStampedModel


INVITE_VALID_FOR = datetime.timedelta(days=7)


def generate_invite_token():
    return secrets.token_urlsafe(32)


def default_invite_expiry():
    return timezone.now() + INVITE_VALID_FOR


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
        try:
            self.whatsapp_url_template.format(phone="", message="")
        except (AttributeError, IndexError, KeyError, ValueError) as exc:
            raise ValidationError(
                {
                    "whatsapp_url_template": (
                        "Use only valid {phone} and {message} placeholders."
                    )
                }
            ) from exc

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


class OrganizationInvite(TimeStampedModel):
    """A single-use link that lets an employee join an existing organization.

    Owner is deliberately not invitable: it is established when the workspace
    is created, so an Admin cannot use an invite to escalate past their own
    role. Promoting someone to Owner stays a Django admin action.
    """

    class Role(models.TextChoices):
        ADMIN = "Admin", "Admin"
        APPROVER = "Approver", "Approver"
        OPERATOR = "Operator", "Operator"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invites"
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.OPERATOR
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_invite_token,
        editable=False,
    )
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.PROTECT, related_name="created_invites"
    )
    expires_at = models.DateTimeField(default=default_invite_expiry)
    used_by = models.OneToOneField(
        CustomUser,
        on_delete=models.SET_NULL,
        related_name="accepted_invite",
        blank=True,
        null=True,
    )
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("organization", "used_at"), name="invite_org_used_idx"
            )
        ]

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self):
        return not (self.is_used or self.is_revoked or self.is_expired)

    @property
    def state(self):
        if self.is_used:
            return "used"
        if self.is_revoked:
            return "revoked"
        if self.is_expired:
            return "expired"
        return "active"

    def clean(self):
        super().clean()
        if (
            self.created_by_id
            and self.created_by.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"created_by": "Invites must be created inside your organization."}
            )

    def __str__(self):
        return f"{self.get_role_display()} invite for {self.organization}"
