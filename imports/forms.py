from django import forms


class ReplacementUploadForm(forms.Form):
    """Re-upload of a corrected file for an import that failed validation."""

    csv_file = forms.FileField(
        label="Corrected CSV file",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv"}),
    )
    title = forms.CharField(max_length=230, label="Campaign title")

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a CSV file.")
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("CSV files may not exceed 10 MB.")
        return uploaded
