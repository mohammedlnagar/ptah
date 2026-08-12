from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .formatting import validate_template_content
from .models import (
    CampaignMessage,
    MessageHandoffEvent,
    MessageTemplate,
    MessageTemplateRevision,
)


@transaction.atomic
def create_template_revision(*, template, user, content, make_current=True):
    if not user.organization_id or user.organization_id != template.organization_id:
        raise PermissionDenied("The template belongs to another organization.")
    validate_template_content(content)
    MessageTemplate.objects.select_for_update().get(pk=template.pk)
    last_version = (
        MessageTemplateRevision.objects.filter(template=template).aggregate(
            maximum=Max("version")
        )["maximum"]
        or 0
    )
    if make_current:
        MessageTemplateRevision.objects.filter(template=template, is_current=True).update(
            is_current=False
        )
    revision = MessageTemplateRevision(
        organization=template.organization,
        template=template,
        version=last_version + 1,
        content=content,
        created_by=user,
        is_current=make_current,
    )
    revision.full_clean()
    revision.save()
    if make_current:
        template.current_revision = revision
        template.content = content
        template.approval_status = MessageTemplate.ApprovalStatus.DRAFT
        template.approved_by = None
        template.approved_at = None
        template.save(
            update_fields=(
                "current_revision",
                "content",
                "approval_status",
                "approved_by",
                "approved_at",
                "updated_at",
            )
        )
    return revision


def _locked_revision(revision, user):
    revision = MessageTemplateRevision.objects.select_for_update().select_related(
        "template"
    ).get(pk=revision.pk)
    if not user.organization_id or user.organization_id != revision.organization_id:
        raise PermissionDenied("The template revision belongs to another organization.")
    return revision


@transaction.atomic
def submit_template_revision(*, revision, user):
    """Move an author's draft into the approval queue.

    Gated on add_messagetemplate rather than change_messagetemplate so the
    person who wrote the draft can hand it over for review.
    """
    revision = _locked_revision(revision, user)
    if not user.has_perm("messaging.add_messagetemplate"):
        raise PermissionDenied("You cannot submit message templates for review.")
    if revision.approval_status not in {
        MessageTemplateRevision.ApprovalStatus.DRAFT,
        MessageTemplateRevision.ApprovalStatus.REJECTED,
    }:
        raise ValidationError("Only a draft or rejected revision can be submitted.")
    revision.approval_status = MessageTemplateRevision.ApprovalStatus.PENDING
    revision.rejection_reason = ""
    revision.full_clean()
    revision.save(
        update_fields=("approval_status", "rejection_reason", "updated_at")
    )
    template = revision.template
    if revision.is_current:
        template.approval_status = MessageTemplate.ApprovalStatus.PENDING
        template.save(update_fields=("approval_status", "updated_at"))
    return revision


@transaction.atomic
def reject_template_revision(*, revision, user, reason=""):
    revision = _locked_revision(revision, user)
    if not user.has_perm("messaging.approve_messagetemplate"):
        raise PermissionDenied("You cannot approve message templates.")
    if revision.approval_status == MessageTemplateRevision.ApprovalStatus.APPROVED:
        raise ValidationError("An approved revision cannot be rejected.")
    revision.approval_status = MessageTemplateRevision.ApprovalStatus.REJECTED
    revision.rejection_reason = reason
    revision.approved_by = None
    revision.approved_at = None
    revision.full_clean()
    revision.save(
        update_fields=(
            "approval_status",
            "rejection_reason",
            "approved_by",
            "approved_at",
            "updated_at",
        )
    )
    template = revision.template
    if revision.is_current:
        template.approval_status = MessageTemplate.ApprovalStatus.REJECTED
        template.approved_by = None
        template.approved_at = None
        template.save(
            update_fields=(
                "approval_status",
                "approved_by",
                "approved_at",
                "updated_at",
            )
        )
    return revision


@transaction.atomic
def approve_template_revision(*, revision, user):
    revision = MessageTemplateRevision.objects.select_for_update().select_related(
        "template"
    ).get(pk=revision.pk)
    if not user.organization_id or user.organization_id != revision.organization_id:
        raise PermissionDenied("The template revision belongs to another organization.")
    if not user.has_perm("messaging.approve_messagetemplate"):
        raise PermissionDenied("You cannot approve message templates.")
    revision.approval_status = MessageTemplateRevision.ApprovalStatus.APPROVED
    revision.approved_by = user
    revision.approved_at = timezone.now()
    revision.rejection_reason = ""
    revision.full_clean()
    revision.save(
        update_fields=(
            "approval_status",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "updated_at",
        )
    )
    template = revision.template
    if revision.is_current:
        template.approval_status = MessageTemplate.ApprovalStatus.APPROVED
        template.approved_by = user
        template.approved_at = revision.approved_at
        template.save(
            update_fields=(
                "approval_status",
                "approved_by",
                "approved_at",
                "updated_at",
            )
        )
    return revision


def _ensure_message_scope(message, user):
    if not user.organization_id or user.organization_id != message.organization_id:
        raise PermissionDenied("The message belongs to another organization.")


@transaction.atomic
def record_message_content_edit(*, message, user, rendered_content):
    message = CampaignMessage.objects.select_for_update().get(pk=message.pk)
    _ensure_message_scope(message, user)
    rendered_content = rendered_content.strip()
    if not rendered_content:
        raise ValidationError({"rendered_content": "Message cannot be empty."})
    message.rendered_content = rendered_content
    message.save(update_fields=("rendered_content", "updated_at"))
    event = MessageHandoffEvent(
        organization=message.organization,
        message=message,
        event_type=MessageHandoffEvent.EventType.CONTENT_EDITED,
        previous_status=message.status,
        new_status=message.status,
        actor=user,
    )
    event.full_clean()
    event.save()
    from reporting.services import refresh_campaign_summary

    refresh_campaign_summary(message.campaign_item.campaign)
    return message


@transaction.atomic
def transition_message_status(
    *, message, user, new_status, event_type=None, metadata=None
):
    message = CampaignMessage.objects.select_for_update().select_related(
        "campaign_item__campaign"
    ).get(pk=message.pk)
    _ensure_message_scope(message, user)
    if new_status not in CampaignMessage.Status.values:
        raise ValidationError({"status": "Invalid message status."})
    previous_status = message.status
    now = timezone.now()
    update_fields = ["status", "updated_at"]
    effective_status = new_status
    if (
        event_type == MessageHandoffEvent.EventType.WHATSAPP_OPENED
        and previous_status
        in {CampaignMessage.Status.SENT, CampaignMessage.Status.SKIPPED}
    ):
        effective_status = previous_status
    message.status = effective_status
    if new_status == CampaignMessage.Status.OPENED:
        message.opened_at = now
        update_fields.append("opened_at")
    if (
        effective_status == CampaignMessage.Status.SENT
        and previous_status != CampaignMessage.Status.SENT
    ):
        message.sent_at = now
        message.sent_by = user
        update_fields.extend(("sent_at", "sent_by"))
    elif (
        previous_status == CampaignMessage.Status.SENT
        and effective_status != CampaignMessage.Status.SENT
    ):
        message.sent_at = None
        message.sent_by = None
        update_fields.extend(("sent_at", "sent_by"))
    message.save(update_fields=update_fields)
    event = MessageHandoffEvent(
        organization=message.organization,
        message=message,
        event_type=event_type or MessageHandoffEvent.EventType.STATUS_CHANGED,
        previous_status=previous_status,
        new_status=effective_status,
        actor=user,
        metadata=metadata or {},
    )
    event.full_clean()
    event.save()
    return message
