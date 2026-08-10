from django import forms

from .models import Campaign, MessageTemplate


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
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
            is_active=True,
        )

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a CSV file.")
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("CSV files may not exceed 10 MB.")
        return uploaded


class MessageTemplateForm(forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ("name", "purpose", "content")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.organization = user.organization
        self.instance.created_by = user

    def save(self, commit=True):
        template = super().save(commit=False)
        template.organization = self.user.organization
        template.created_by = self.user
        if commit:
            template.full_clean()
            template.save()
        return template
