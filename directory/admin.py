from django.contrib import admin

from common.admin import TenantAdminMixin

from .models import Contact, Department, Doctor


@admin.register(Contact)
class ContactAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "phone_number", "mrn", "organization")
    list_filter = ("organization",)
    search_fields = ("name", "phone_number", "mrn", "normalized_mrn")


@admin.register(Department)
class DepartmentAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "code", "organization", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "code")


@admin.register(Doctor)
class DoctorAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "department",
        "phone_number",
        "organization",
        "is_active",
    )
    list_filter = ("organization", "department", "is_active")
    search_fields = ("name", "code", "phone_number")
