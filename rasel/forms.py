from django import forms
from django.db.models import Q

from campaigns.models import Campaign
from messaging.models import MessageTemplate


class CampaignUploadForm(forms.ModelForm):
    csv_file = forms.FileField(
        required=True,
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "form-control"}),
    )

    class Meta:
        model = Campaign
        fields = ("title", "purpose", "template", "csv_file")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.organization = user.organization
        self.instance.created_by = user
        self.fields["template"].queryset = MessageTemplate.objects.filter(
            organization=user.organization,
            is_active=True,
        ).filter(
            Q(
                current_revision__approval_status=MessageTemplate.ApprovalStatus.APPROVED
            )
            | Q(
                current_revision__isnull=True,
                approval_status=MessageTemplate.ApprovalStatus.APPROVED,
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        template = cleaned_data.get("template")
        purpose = cleaned_data.get("purpose")
        if template and purpose and template.purpose not in {
            purpose,
            MessageTemplate.Purpose.GENERAL,
        }:
            self.add_error(
                "template", "Select a template matching the campaign purpose."
            )
        return cleaned_data

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a CSV file.")
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("CSV files may not exceed 10 MB.")
        return uploaded
