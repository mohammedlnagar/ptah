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
    OrganizationSubscription,
    SubscriptionPlan,
)


class CustomUserCreationForm(UserCreationForm):
    organization_name = forms.CharField(max_length=200, label="Organization name")

    class Meta:
        model = CustomUser
        fields = ("organization_name", "username", "email", "mobile_number", "password1", "password2")

    def clean_mobile_number(self):
        value = (self.cleaned_data.get("mobile_number") or "").strip()
        if value and not re.fullmatch(r"\+?[1-9]\d{6,14}", value):
            raise forms.ValidationError("Enter a valid international phone number.")
        return value

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


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email")


class CustomUserUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email", "mobile_number")

    def clean_mobile_number(self):
        value = (self.cleaned_data.get("mobile_number") or "").strip()
        if value and not re.fullmatch(r"\+?[1-9]\d{6,14}", value):
            raise forms.ValidationError("Enter a valid international phone number.")
        return value
