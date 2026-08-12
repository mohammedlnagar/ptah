from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .models import CustomUser


ROLE_PERMISSION_PREFIXES = {
    "Owner": (
        "account.view_customuser",
        "account.add_customuser",
        "account.change_customuser",
        "account.delete_customuser",
        "account.view_organization",
        "account.change_organization",
        "account.view_organizationsubscription",
        "account.view_subscriptionplan",
        "account.add_organizationinvite",
        "account.change_organizationinvite",
        "account.view_organizationinvite",
        "rasel.",
        "appointments.",
        "messaging.",
        "imports.",
        "directory.",
        "campaigns.",
    ),
    "Admin": (
        "account.view_",
        # A tenant Admin runs day-to-day onboarding: inviting colleagues and
        # approving them. Creating Owners stays out of reach by design.
        "account.change_customuser",
        "account.add_organizationinvite",
        "account.change_organizationinvite",
        "rasel.",
        "appointments.",
        "messaging.",
        "imports.",
        "directory.",
        "campaigns.",
    ),
    "Approver": (
        "rasel.view_",
        "messaging.change_messagetemplate",
        "messaging.approve_messagetemplate",
        "messaging.view_",
        "imports.view_",
        "directory.view_",
        "campaigns.view_",
    ),
    "Operator": (
        "rasel.view_",
        "campaigns.add_campaign",
        "campaigns.change_campaign",
        "imports.add_importbatch",
        "imports.change_importbatch",
        "campaigns.add_campaignitem",
        "campaigns.change_campaignitem",
        "messaging.add_campaignmessage",
        "messaging.change_campaignmessage",
        "messaging.add_messagetemplate",
        "campaigns.change_doctorsummary",
        "appointments.view_",
        "messaging.view_",
        "imports.view_",
        "directory.view_",
        "directory.add_contact",
        "directory.change_contact",
        "campaigns.view_",
    ),
}


@receiver(post_migrate)
def configure_role_permissions(**kwargs):
    if not apps.ready:
        return

    permissions = list(
        Permission.objects.select_related("content_type").filter(
            content_type__app_label__in=(
                "account",
                "rasel",
                "appointments",
                "messaging",
                "imports",
                "directory",
                "campaigns",
            )
        )
    )
    for role_name, prefixes in ROLE_PERMISSION_PREFIXES.items():
        group, _ = Group.objects.get_or_create(name=role_name)
        selected = []
        for permission in permissions:
            qualified = f"{permission.content_type.app_label}.{permission.codename}"
            if any(qualified.startswith(prefix) for prefix in prefixes):
                selected.append(permission)
        group.permissions.set(selected)

    CustomUser.objects.filter(
        groups__name__in=("Owner", "Admin", "Approver")
    ).update(is_staff=True)


@receiver(m2m_changed, sender=CustomUser.groups.through)
def synchronize_staff_access(sender, instance, action, **kwargs):
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    should_be_staff = instance.is_superuser or instance.groups.filter(
        name__in=("Owner", "Admin", "Approver")
    ).exists()
    if instance.is_staff != should_be_staff:
        CustomUser.objects.filter(pk=instance.pk).update(is_staff=should_be_staff)
        instance.is_staff = should_be_staff
