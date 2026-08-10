from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver


ROLE_PERMISSION_PREFIXES = {
    "Owner": (
        "account.view_customuser",
        "account.add_customuser",
        "account.change_customuser",
        "account.delete_customuser",
        "account.view_userprofile",
        "account.add_userprofile",
        "account.change_userprofile",
        "account.delete_userprofile",
        "account.view_organization",
        "account.change_organization",
        "account.view_organizationsubscription",
        "account.view_subscriptionplan",
        "rasel.",
    ),
    "Admin": ("account.view_", "rasel."),
    "Approver": (
        "rasel.view_",
        "rasel.change_messagetemplate",
        "rasel.approve_messagetemplate",
    ),
    "Operator": (
        "rasel.view_",
        "rasel.add_campaign",
        "rasel.change_campaign",
        "rasel.add_importbatch",
        "rasel.change_importbatch",
        "rasel.add_campaignitem",
        "rasel.change_campaignitem",
        "rasel.add_campaignmessage",
        "rasel.change_campaignmessage",
        "rasel.add_contact",
        "rasel.change_contact",
    ),
}


@receiver(post_migrate)
def configure_role_permissions(**kwargs):
    if not apps.ready:
        return

    permissions = list(
        Permission.objects.select_related("content_type").filter(
            content_type__app_label__in=("account", "rasel")
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
