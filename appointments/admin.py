from django.contrib import admin

from common.admin import ReadOnlyTenantAdminMixin

from .models import Appointment, AppointmentStatusEvent


@admin.register(Appointment)
class AppointmentAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = ("contact", "doctor", "scheduled_at", "status", "organization")
    list_filter = ("organization", "status")
    search_fields = ("contact__name", "contact__phone_number", "contact__mrn")


@admin.register(AppointmentStatusEvent)
class AppointmentStatusEventAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "appointment",
        "previous_status",
        "new_status",
        "changed_by",
        "created_at",
    )
    list_filter = ("organization", "new_status")
