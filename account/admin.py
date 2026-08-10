from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    CustomUser,
    Organization,
    OrganizationSubscription,
    SubscriptionPlan,
    UserProfile,
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Organization", {"fields": ("organization", "mobile_number")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Organization", {"fields": ("email", "organization", "mobile_number")}),
    )
    list_display = ("email", "username", "organization", "is_active", "is_staff")
    list_filter = ("organization", "is_active", "is_staff")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser and request.user.organization_id is None:
            return queryset
        return queryset.filter(organization=request.user.organization)

    def save_model(self, request, obj, form, change):
        if not (request.user.is_superuser and request.user.organization_id is None):
            obj.organization = request.user.organization
        super().save_model(request, obj, form, change)


class OrganizationScopedAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser and request.user.organization_id is None:
            return queryset
        organization_field = "pk" if self.model is Organization else "organization"
        return queryset.filter(**{organization_field: request.user.organization_id})


@admin.register(Organization)
class OrganizationAdmin(OrganizationScopedAdmin):
    list_display = ("name", "slug", "is_active")


@admin.register(OrganizationSubscription)
class OrganizationSubscriptionAdmin(OrganizationScopedAdmin):
    list_display = ("organization", "plan", "status", "starts_on", "ends_on")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser and request.user.organization_id is None:
            return queryset
        return queryset.filter(user__organization=request.user.organization)


admin.site.register(SubscriptionPlan)
