from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError

from common.admin import ReadOnlyTenantAdminMixin, TenantAdminMixin

from .models import (
    CampaignMessage,
    MessageHandoffEvent,
    MessageTemplate,
    MessageTemplateRevision,
)
from .services import approve_template_revision


@admin.register(MessageTemplate)
class MessageTemplateAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "organization", "purpose", "approval_status", "is_active")
    list_filter = ("organization", "purpose", "approval_status", "is_active")
    actions = ("approve_current_revision",)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                "content",
                "approval_status",
                "approved_by",
                "approved_at",
                "current_revision",
            )
        return ()

    def has_add_permission(self, request):
        return False

    @admin.action(description="Approve current template revision")
    def approve_current_revision(self, request, queryset):
        approved = 0
        for template in queryset.select_related("current_revision"):
            if not template.current_revision_id:
                continue
            try:
                approve_template_revision(
                    revision=template.current_revision,
                    user=request.user,
                )
            except (PermissionDenied, ValidationError) as exc:
                self.message_user(request, str(exc), level="error")
                continue
            approved += 1
        self.message_user(request, f"Approved {approved} template revision(s).")


@admin.register(CampaignMessage)
class CampaignMessageAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = ("campaign_item", "status", "organization", "updated_at")
    list_filter = ("organization", "status")
    search_fields = (
        "campaign_item__patient_name_snapshot",
        "campaign_item__phone_number_snapshot",
        "campaign_item__mrn_snapshot",
    )


@admin.register(MessageTemplateRevision)
class MessageTemplateRevisionAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "template",
        "version",
        "approval_status",
        "is_current",
        "created_by",
    )
    list_filter = ("organization", "approval_status", "is_current")
    readonly_fields = ("version", "approved_by", "approved_at")



@admin.register(MessageHandoffEvent)
class MessageHandoffEventAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = ("message", "event_type", "actor", "created_at")
    list_filter = ("organization", "event_type")
