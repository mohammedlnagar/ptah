from django.contrib import admin


class TenantAdminMixin:
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser and request.user.organization_id is None:
            return queryset
        return queryset.filter(organization=request.user.organization)

    def save_model(self, request, obj, form, change):
        if not (request.user.is_superuser and request.user.organization_id is None):
            obj.organization = request.user.organization
        obj.full_clean()
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if request.user.is_superuser and request.user.organization_id is None:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        related_model = db_field.remote_field.model
        if db_field.name == "organization":
            kwargs["queryset"] = related_model.objects.filter(
                pk=request.user.organization_id
            )
        elif any(
            field.name == "organization" for field in related_model._meta.fields
        ):
            kwargs["queryset"] = related_model.objects.filter(
                organization=request.user.organization
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ReadOnlyTenantAdminMixin(TenantAdminMixin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
