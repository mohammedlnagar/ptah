from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import TenantModel, validate_related_organizations


class MessageTemplate(TenantModel):
    class Purpose(models.TextChoices):
        APPOINTMENT = "appointment", "Appointment reminder"
        MARKETING = "marketing", "Marketing"
        GENERAL = "general", "General"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_message_templates",
    )
    name = models.CharField(max_length=255)
    purpose = models.CharField(
        max_length=20, choices=Purpose.choices, default=Purpose.APPOINTMENT
    )
    content = models.TextField()
    approval_status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_message_templates",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    current_revision = models.ForeignKey(
        "MessageTemplateRevision",
        on_delete=models.PROTECT,
        related_name="current_for_templates",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "rasel_messagetemplate"
        ordering = ("name",)
        permissions = [("approve_messagetemplate", "Can approve message templates")]
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"),
                name="unique_template_name_per_org",
            ),
            models.CheckConstraint(
                condition=Q(purpose__in=("appointment", "marketing", "general")),
                name="valid_template_purpose",
            ),
            models.CheckConstraint(
                condition=Q(
                    approval_status__in=("draft", "pending", "approved", "rejected")
                ),
                name="valid_template_approval",
            ),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(
            self, "created_by", "approved_by", "current_revision"
        )
        if (
            self.current_revision_id
            and self.current_revision.template_id != self.pk
        ):
            raise ValidationError(
                {"current_revision": "Select a revision of this template."}
            )

    def __str__(self):
        return self.name


class MessageTemplateRevision(TenantModel):
    class ApprovalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    template = models.ForeignKey(
        MessageTemplate, on_delete=models.CASCADE, related_name="revisions"
    )
    version = models.PositiveIntegerField()
    content = models.TextField()
    approval_status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_template_revisions",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_template_revisions",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ("template", "-version")
        constraints = [
            models.UniqueConstraint(
                fields=("template", "version"), name="unique_template_revision"
            ),
            models.UniqueConstraint(
                fields=("template",),
                condition=Q(is_current=True),
                name="unique_current_template_revision",
            ),
            models.CheckConstraint(
                condition=Q(
                    approval_status__in=("draft", "pending", "approved", "rejected")
                ),
                name="valid_revision_approval",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "approval_status"),
                name="revision_org_status_idx",
            )
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(
            self, "template", "created_by", "approved_by"
        )
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if (
                previous
                and previous.approval_status == self.ApprovalStatus.APPROVED
                and (
                    previous.content != self.content
                    or previous.template_id != self.template_id
                    or previous.version != self.version
                )
            ):
                raise ValidationError("Approved template revisions are immutable.")
        if self.approval_status == self.ApprovalStatus.APPROVED:
            if not self.approved_by_id or not self.approved_at:
                raise ValidationError(
                    "Approved revisions require an approver and approval time."
                )

    def __str__(self):
        return f"{self.template} v{self.version}"


class CampaignMessage(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        OPENED = "opened", "WhatsApp opened"
        SENT = "operator_marked_sent", "Operator marked sent"
        SKIPPED = "skipped", "Skipped"

    campaign_item = models.OneToOneField(
        "campaigns.CampaignItem", on_delete=models.CASCADE, related_name="message"
    )
    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.SET_NULL,
        related_name="rendered_messages",
        blank=True,
        null=True,
    )
    template_revision = models.ForeignKey(
        MessageTemplateRevision,
        on_delete=models.SET_NULL,
        related_name="rendered_messages",
        blank=True,
        null=True,
    )
    rendered_content = models.TextField()
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.PENDING
    )
    opened_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_campaign_messages",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "rasel_campaignmessage"
        indexes = [
            models.Index(
                fields=("organization", "status"), name="message_org_status_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "pending",
                        "opened",
                        "operator_marked_sent",
                        "skipped",
                    )
                ),
                name="valid_campaign_message_status",
            )
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(
            self, "campaign_item", "template", "template_revision", "sent_by"
        )
        if (
            self.template_revision_id
            and self.template_revision.template_id != self.template_id
        ):
            raise ValidationError(
                {"template_revision": "Select a revision of the message template."}
            )
        campaign = self.campaign_item.campaign if self.campaign_item_id else None
        if campaign and campaign.template_id and campaign.template_id != self.template_id:
            raise ValidationError(
                {"template": "Use the template selected for the campaign."}
            )
        if (
            campaign
            and campaign.template_revision_id
            and campaign.template_revision_id != self.template_revision_id
        ):
            raise ValidationError(
                {"template_revision": "Use the revision selected for the campaign."}
            )

    def whatsapp_url(self):
        template = self.organization.whatsapp_url_template
        phone = "".join(
            character
            for character in self.campaign_item.phone_number_snapshot
            if character.isdigit()
        )
        return template.format(
            phone=quote(phone, safe=""),
            message=quote(self.rendered_content, safe=""),
        )

    def __str__(self):
        return f"Message for {self.campaign_item.patient_name_snapshot}"


class MessageHandoffEvent(TenantModel):
    class EventType(models.TextChoices):
        CONTENT_EDITED = "content_edited", "Content edited"
        WHATSAPP_OPENED = "whatsapp_opened", "WhatsApp opened"
        STATUS_CHANGED = "status_changed", "Status changed"

    message = models.ForeignKey(
        CampaignMessage,
        on_delete=models.CASCADE,
        related_name="handoff_events",
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    previous_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="message_handoff_events",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("organization", "created_at"), name="handoff_org_created_idx"
            ),
            models.Index(fields=("message", "created_at"), name="handoff_message_idx"),
        ]

    def clean(self):
        super().clean()
        validate_related_organizations(self, "message", "actor")

    def __str__(self):
        return f"{self.message} - {self.get_event_type_display()}"
