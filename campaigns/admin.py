from django.contrib import admin

from common.admin import ReadOnlyTenantAdminMixin

from .models import Campaign, CampaignItem, DoctorSummary


@admin.register(Campaign)
class CampaignAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = ("title", "organization", "purpose", "status", "created_at")
    list_filter = ("organization", "purpose", "status")
    search_fields = ("title",)


@admin.register(CampaignItem)
class CampaignItemAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "patient_name_snapshot",
        "campaign",
        "doctor_name_snapshot",
        "appointment_status",
    )
    list_filter = ("organization", "appointment_status")
    search_fields = (
        "patient_name_snapshot",
        "phone_number_snapshot",
        "mrn_snapshot",
        "doctor_name_snapshot",
    )


@admin.register(DoctorSummary)
class DoctorSummaryAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = ("campaign", "doctor", "status", "organization", "updated_at")
    list_filter = ("organization", "status")
    search_fields = ("campaign__title", "doctor__name")
