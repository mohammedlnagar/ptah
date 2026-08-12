from django import forms

from .models import Department, Doctor
from .normalization import canonical_key, clean_display_text


class TenantModelForm(forms.ModelForm):
    """Binds the form to one organization and scopes its related querysets."""

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.instance.organization = organization

    def _post_clean(self):
        # Assigned before validation so model clean() can compare organizations.
        self.instance.organization = self.organization
        super()._post_clean()


    def _reject_duplicate(self, model, field, value, message):
        """Validate a uniqueness rule keyed on a normalized, non-editable column.

        Django excludes those columns from ModelForm.validate_unique because
        they are not form fields, so without this the duplicate would only be
        caught by the database and surface as a 500.
        """
        normalized = canonical_key(value)
        if not normalized:
            return
        duplicates = model.objects.for_organization(self.organization).filter(
            **{field: normalized}
        )
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(message)


class DepartmentForm(TenantModelForm):
    class Meta:
        model = Department
        fields = ("name", "code", "is_active")

    def clean_name(self):
        name = clean_display_text(self.cleaned_data["name"])
        self._reject_duplicate(
            Department,
            "normalized_name",
            name,
            "A department with this name already exists.",
        )
        return name


class DoctorForm(TenantModelForm):
    class Meta:
        model = Doctor
        fields = ("name", "department", "code", "phone_number", "is_active")

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, organization=organization, **kwargs)
        self.fields["department"].queryset = Department.objects.for_organization(
            organization
        ).filter(is_active=True)
        self.fields["department"].required = False

    def clean_code(self):
        code = clean_display_text(self.cleaned_data.get("code"))
        self._reject_duplicate(
            Doctor,
            "normalized_code",
            code,
            "Another doctor already uses this code.",
        )
        return code
