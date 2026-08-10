from django.contrib import admin

from .models import (
    Campaign,
    CampaignItem,
    CampaignMessage,
    Contact,
    Department,
    Doctor,
    DoctorSummary,
    ImportBatch,
    MessageTemplate,
)


class TenantAdminMixin:
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser and request.user.organization_id is None:
            return queryset
        return queryset.filter(organization=request.user.organization)

    def save_model(self, request, obj, form, change):
        if not (request.user.is_superuser and request.user.organization_id is None):
            obj.organization = request.user.organization
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if request.user.is_superuser and request.user.organization_id is None:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        related_model = db_field.remote_field.model
        if db_field.name == "organization":
            kwargs["queryset"] = related_model.objects.filter(pk=request.user.organization_id)
        elif hasattr(related_model, "organization_id") or any(
            field.name == "organization" for field in related_model._meta.fields
        ):
            kwargs["queryset"] = related_model.objects.filter(
                organization=request.user.organization
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Campaign)
class CampaignAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("title", "organization", "purpose", "status", "created_at")
    list_filter = ("organization", "purpose", "status")
    search_fields = ("title",)


@admin.register(CampaignItem)
class CampaignItemAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("patient_name_snapshot", "campaign", "doctor_name_snapshot", "appointment_status")
    list_filter = ("organization", "appointment_status")
    search_fields = ("patient_name_snapshot", "phone_number_snapshot", "mrn_snapshot", "doctor_name_snapshot")


@admin.register(MessageTemplate)
class MessageTemplateAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "organization", "purpose", "approval_status", "is_active")
    list_filter = ("organization", "purpose", "approval_status", "is_active")


for model in (CampaignMessage, Contact, Department, Doctor, DoctorSummary, ImportBatch):
    admin.site.register(model, type(f"{model.__name__}Admin", (TenantAdminMixin, admin.ModelAdmin), {}))
