from django.contrib import admin

from common.admin import ReadOnlyTenantAdminMixin

from .models import ImportBatch, ImportIssue


@admin.register(ImportBatch)
class ImportBatchAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "original_filename",
        "purpose",
        "status",
        "row_count",
        "organization",
        "created_at",
    )
    list_filter = ("organization", "purpose", "status")
    search_fields = ("original_filename", "sha256")
    readonly_fields = (
        "sha256",
        "row_count",
        "imported_count",
        "error_count",
        "errors",
        "processed_at",
    )


@admin.register(ImportIssue)
class ImportIssueAdmin(ReadOnlyTenantAdminMixin, admin.ModelAdmin):
    list_display = ("batch", "row_number", "column", "message", "created_at")
    list_filter = ("organization", "column")
    search_fields = ("batch__original_filename", "message")
