from django import forms
from django.db import transaction

from .formatting import validate_template_content
from .models import MessageTemplate
from .services import create_template_revision


class MessageTemplateForm(forms.ModelForm):
    """Creates a template, or records an edit as a new revision.

    Editing always produces a new revision rather than mutating the current
    one, so approved copy that campaigns already rendered from stays intact.
    """

    class Meta:
        model = MessageTemplate
        fields = ("name", "purpose", "content")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.organization = user.organization
        if not self.instance.pk:
            self.instance.created_by = user

    def clean_content(self):
        content = self.cleaned_data["content"]
        validate_template_content(content)
        return content

    @transaction.atomic
    def save(self, commit=True):
        template = super().save(commit=False)
        template.organization = self.user.organization
        if not template.created_by_id:
            template.created_by = self.user
        if not commit:
            return template
        template.full_clean()
        template.save()
        current = template.current_revision
        if current is None or current.content != template.content:
            create_template_revision(
                template=template,
                user=self.user,
                content=template.content,
            )
        return template
