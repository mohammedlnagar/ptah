import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    CustomUser,
    Organization,
    OrganizationInvite,
    OrganizationSubscription,
    SubscriptionPlan,
)


class MobileNumberFieldMixin:
    def clean_mobile_number(self):
        value = (self.cleaned_data.get("mobile_number") or "").strip()
        if value and not re.fullmatch(r"\+?[1-9]\d{6,14}", value):
            raise forms.ValidationError("Enter a valid international phone number.")
        return value


class CustomUserCreationForm(MobileNumberFieldMixin, UserCreationForm):
    """Creates a brand-new organization with the signing-up user as its Owner."""

    organization_name = forms.CharField(max_length=200, label="Organization name")

    class Meta:
        model = CustomUser
        fields = ("organization_name", "username", "email", "mobile_number", "password1", "password2")

    def _unique_slug(self, name):
        base = slugify(name)[:180] or "organization"
        candidate = base
        suffix = 2
        while Organization.objects.filter(slug=candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("Organization signup must be committed atomically.")
        organization_name = self.cleaned_data["organization_name"].strip()
        organization = Organization.objects.create(
            name=organization_name,
            slug=self._unique_slug(organization_name),
        )
        plan, _ = SubscriptionPlan.objects.get_or_create(
            code="starter",
            defaults={"name": "Starter", "monthly_price": 0, "max_users": 5, "max_monthly_campaigns": 20},
        )
        OrganizationSubscription.objects.create(
            organization=organization,
            plan=plan,
            status=OrganizationSubscription.Status.TRIAL,
            starts_on=timezone.localdate(),
        )
        user = super().save(commit=False)
        user.organization = organization
        user.save()
        owner_group, _ = Group.objects.get_or_create(name="Owner")
        user.groups.add(owner_group)
        return user


class InvitedUserCreationForm(MobileNumberFieldMixin, UserCreationForm):
    """Joins an employee to the organization named on their invite.

    The organization and role come from the invite rather than from user
    input, and the account stays inactive until an admin approves it.
    """

    class Meta:
        model = CustomUser
        fields = ("username", "email", "mobile_number", "password1", "password2")

    def __init__(self, *args, invite=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invite = invite

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("Invited signup must be committed atomically.")
        # Re-read under a row lock so two people cannot consume the same link.
        invite = OrganizationInvite.objects.select_for_update().get(
            pk=self.invite.pk
        )
        if not invite.is_usable:
            raise forms.ValidationError("This invitation is no longer valid.")
        user = super().save(commit=False)
        user.organization = invite.organization
        user.is_active = False
        user.save()
        group, _ = Group.objects.get_or_create(name=invite.role)
        user.groups.add(group)
        invite.used_by = user
        invite.used_at = timezone.now()
        invite.save(update_fields=("used_by", "used_at", "updated_at"))
        return user


class OrganizationInviteForm(forms.ModelForm):
    class Meta:
        model = OrganizationInvite
        fields = ("role",)


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email")


class CustomUserUpdateForm(MobileNumberFieldMixin, forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email", "mobile_number")
