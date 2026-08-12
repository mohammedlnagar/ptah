from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from common.access import tenant_or_403

from .forms import MessageTemplateForm
from .formatting import PLACEHOLDER_NAMES
from .models import MessageTemplate, MessageTemplateRevision
from .services import (
    approve_template_revision,
    reject_template_revision,
    submit_template_revision,
)


def _revision_for_organization(organization, revision_id):
    return get_object_or_404(
        MessageTemplateRevision.objects.for_organization(organization).select_related(
            "template", "created_by"
        ),
        pk=revision_id,
    )


@login_required
@permission_required("messaging.view_messagetemplate", raise_exception=True)
def template_approvals(request):
    organization = tenant_or_403(request)
    revisions = (
        MessageTemplateRevision.objects.for_organization(organization)
        .filter(is_current=True)
        .select_related("template", "created_by", "approved_by")
        .order_by("template__name")
    )
    awaiting = [
        revision
        for revision in revisions
        if revision.approval_status == MessageTemplateRevision.ApprovalStatus.PENDING
    ]
    drafts = [
        revision
        for revision in revisions
        if revision.approval_status
        in {
            MessageTemplateRevision.ApprovalStatus.DRAFT,
            MessageTemplateRevision.ApprovalStatus.REJECTED,
        }
    ]
    settled = [
        revision
        for revision in revisions
        if revision.approval_status == MessageTemplateRevision.ApprovalStatus.APPROVED
    ]
    return render(
        request,
        "messaging/template_approvals.html",
        {
            "awaiting_review": awaiting,
            "drafts": drafts,
            "approved": settled,
            "can_approve": request.user.has_perm("messaging.approve_messagetemplate"),
            "can_submit": request.user.has_perm("messaging.add_messagetemplate"),
        },
    )


@login_required
@permission_required("messaging.add_messagetemplate", raise_exception=True)
def template_create(request):
    organization = tenant_or_403(request)
    if request.method == "POST":
        form = MessageTemplateForm(request.POST, user=request.user)
        if form.is_valid():
            template = form.save()
            messages.success(
                request, f"“{template.name}” saved as a draft."
            )
            return redirect("template_approvals")
    else:
        form = MessageTemplateForm(user=request.user)
    return render(
        request,
        "messaging/template_form.html",
        {
            "form": form,
            "heading": "New message template",
            "placeholders": PLACEHOLDER_NAMES,
        },
    )


@login_required
@permission_required("messaging.change_messagetemplate", raise_exception=True)
def template_edit(request, template_id):
    organization = tenant_or_403(request)
    template = get_object_or_404(
        MessageTemplate.objects.for_organization(organization), pk=template_id
    )
    if request.method == "POST":
        form = MessageTemplateForm(
            request.POST, instance=template, user=request.user
        )
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"“{template.name}” updated. Edits start a new draft revision.",
            )
            return redirect("template_approvals")
    else:
        form = MessageTemplateForm(instance=template, user=request.user)
    return render(
        request,
        "messaging/template_form.html",
        {
            "form": form,
            "heading": f"Edit {template.name}",
            "template": template,
            "placeholders": PLACEHOLDER_NAMES,
        },
    )


@login_required
@require_POST
def submit_template(request, revision_id):
    organization = tenant_or_403(request)
    revision = _revision_for_organization(organization, revision_id)
    try:
        submit_template_revision(revision=revision, user=request.user)
    except PermissionDenied:
        raise
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request, f"“{revision.template.name}” was sent for review."
        )
    return redirect("template_approvals")


@login_required
@require_POST
def approve_template(request, revision_id):
    organization = tenant_or_403(request)
    revision = _revision_for_organization(organization, revision_id)
    try:
        approve_template_revision(revision=revision, user=request.user)
    except PermissionDenied:
        raise
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request, f"“{revision.template.name}” is approved and ready to use."
        )
    return redirect("template_approvals")


@login_required
@require_POST
def reject_template(request, revision_id):
    organization = tenant_or_403(request)
    revision = _revision_for_organization(organization, revision_id)
    reason = (request.POST.get("reason") or "").strip()[:500]
    try:
        reject_template_revision(
            revision=revision, user=request.user, reason=reason
        )
    except PermissionDenied:
        raise
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request, f"“{revision.template.name}” was sent back to the author."
        )
    return redirect("template_approvals")
