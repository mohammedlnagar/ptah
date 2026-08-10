import datetime

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q
from django.utils.text import slugify


DEFAULT_GROUPS = ("Owner", "Admin", "Approver", "Operator")


def create_legacy_tenant(apps, schema_editor):
    Organization = apps.get_model("account", "Organization")
    SubscriptionPlan = apps.get_model("account", "SubscriptionPlan")
    OrganizationSubscription = apps.get_model("account", "OrganizationSubscription")
    CustomUser = apps.get_model("account", "CustomUser")
    UserProfile = apps.get_model("account", "UserProfile")
    Group = apps.get_model("auth", "Group")

    plan, _ = SubscriptionPlan.objects.get_or_create(
        code="legacy",
        defaults={
            "name": "Legacy",
            "monthly_price": 0,
            "max_users": 1000,
            "max_monthly_campaigns": 1000,
            "is_active": True,
        },
    )
    organization, _ = Organization.objects.get_or_create(
        slug="legacy-organization",
        defaults={"name": "Legacy Organization", "timezone": "Asia/Dubai"},
    )
    OrganizationSubscription.objects.get_or_create(
        organization=organization,
        defaults={
            "plan": plan,
            "status": "active",
            "starts_on": datetime.date.today(),
        },
    )
    CustomUser.objects.filter(organization__isnull=True).update(organization=organization)
    UserProfile.objects.filter(legacy_role__isnull=True).update(legacy_role="")

    groups = {name: Group.objects.get_or_create(name=name)[0] for name in DEFAULT_GROUPS}
    for profile in UserProfile.objects.select_related("user"):
        role = (profile.legacy_role or "").lower()
        if "owner" in role:
            group = groups["Owner"]
        elif "admin" in role:
            group = groups["Admin"]
        elif "approv" in role:
            group = groups["Approver"]
        else:
            group = groups["Operator"]
        profile.user.groups.add(group)


def reverse_legacy_tenant(apps, schema_editor):
    CustomUser = apps.get_model("account", "CustomUser")
    Organization = apps.get_model("account", "Organization")
    Group = apps.get_model("auth", "Group")

    legacy = Organization.objects.filter(slug="legacy-organization").first()
    if legacy:
        CustomUser.objects.filter(organization=legacy).update(organization=None)
    Group.objects.filter(name__in=DEFAULT_GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [("account", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("timezone", models.CharField(default="Asia/Dubai", max_length=64)),
                ("whatsapp_url_template", models.CharField(default="https://wa.me/{phone}?text={message}", help_text="Must contain the {phone} and {message} placeholders.", max_length=500)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.CreateModel(
            name="SubscriptionPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100)),
                ("code", models.SlugField(max_length=50, unique=True)),
                ("monthly_price", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("max_users", models.PositiveIntegerField(default=5)),
                ("max_monthly_campaigns", models.PositiveIntegerField(default=20)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ("monthly_price", "name")},
        ),
        migrations.CreateModel(
            name="OrganizationSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("trial", "Trial"), ("active", "Active"), ("past_due", "Past due"), ("suspended", "Suspended"), ("cancelled", "Cancelled")], default="trial", max_length=20)),
                ("starts_on", models.DateField()),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="subscription", to="account.organization")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions", to="account.subscriptionplan")),
            ],
        ),
        migrations.AddField(
            model_name="customuser",
            name="organization",
            field=models.ForeignKey(blank=True, help_text="Required for tenant employees; platform superusers may be unassigned.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="account.organization"),
        ),
        migrations.RenameField(model_name="userprofile", old_name="role", new_name="legacy_role"),
        migrations.AlterField(model_name="customuser", name="mobile_number", field=models.CharField(blank=True, max_length=20, null=True)),
        migrations.AlterField(model_name="userprofile", name="emergency_contact_phone", field=models.CharField(blank=True, max_length=20, null=True)),
        migrations.AlterModelOptions(name="customuser", options={}),
        migrations.RunPython(create_legacy_tenant, reverse_legacy_tenant),
        migrations.AlterField(model_name="userprofile", name="legacy_role", field=models.CharField(blank=True, help_text="Historical value only. Authorization is managed with Django groups.", max_length=100)),
        migrations.AddConstraint(
            model_name="customuser",
            constraint=models.CheckConstraint(condition=Q(organization__isnull=False) | Q(is_superuser=True), name="employee_requires_organization"),
        ),
        migrations.AddIndex(
            model_name="customuser",
            index=models.Index(fields=["organization", "is_active"], name="user_org_active_idx"),
        ),
        migrations.AddIndex(
            model_name="organizationsubscription",
            index=models.Index(fields=["status", "ends_on"], name="subscription_status_idx"),
        ),
    ]
