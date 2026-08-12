from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from account.services import check_campaign_available
from common.access import tenant_or_403

from .forms import ReplacementUploadForm
from .models import ImportBatch


@login_required
@permission_required("imports.view_importbatch", raise_exception=True)
def import_list(request):
    organization = tenant_or_403(request)
    batches = (
        ImportBatch.objects.for_organization(organization)
        .select_related("uploaded_by", "replaces")
        .prefetch_related("issues")
    )
    return render(
        request,
        "imports/import_list.html",
        {"batches": batches},
    )


@login_required
@permission_required("imports.view_importbatch", raise_exception=True)
def import_detail(request, batch_id):
    organization = tenant_or_403(request)
    batch = get_object_or_404(
        ImportBatch.objects.for_organization(organization).select_related(
            "uploaded_by", "replaces"
        ),
        pk=batch_id,
    )
    replacement_form = None
    if batch.status == ImportBatch.Status.FAILED and request.user.has_perm(
        "imports.add_importbatch"
    ):
        replacement_form = ReplacementUploadForm(
            initial={"title": f"{batch.original_filename} (corrected)"}
        )
    return render(
        request,
        "imports/import_detail.html",
        {
            "batch": batch,
            "issues": batch.issues.all(),
            "replacement_form": replacement_form,
        },
    )


@login_required
@permission_required("imports.add_importbatch", raise_exception=True)
def import_replace(request, batch_id):
    organization = tenant_or_403(request)
    batch = get_object_or_404(
        ImportBatch.objects.for_organization(organization), pk=batch_id
    )
    if batch.status != ImportBatch.Status.FAILED:
        messages.error(request, "Only a failed import can be replaced.")
        return redirect("import_detail", batch_id=batch.pk)
    if hasattr(batch, "replacement"):
        messages.error(request, "This import has already been replaced.")
        return redirect("import_detail", batch_id=batch.pk)

    form = ReplacementUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        # Imported here to avoid a circular import: the CSV handler already
        # depends on this app's models.
        from rasel.utilities.csv_handler import CsvImportError, save_campaign_from_csv

        template = _template_for(batch)
        if template is None:
            messages.error(
                request,
                "The original upload has no template to reuse. Start a new campaign instead.",
            )
            return redirect("import_detail", batch_id=batch.pk)
        try:
            check_campaign_available(organization)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            return redirect("import_detail", batch_id=batch.pk)
        try:
            campaign = save_campaign_from_csv(
                user=request.user,
                file=form.cleaned_data["csv_file"],
                title=form.cleaned_data["title"],
                template=template,
                purpose=batch.purpose,
                replaces=batch,
            )
        except CsvImportError as error:
            messages.error(
                request,
                f"The replacement also failed validation: {error}",
            )
            replacement = ImportBatch.objects.filter(replaces=batch).first()
            return redirect(
                "import_detail", batch_id=replacement.pk if replacement else batch.pk
            )
        messages.success(request, "Replacement imported successfully.")
        return redirect("appointment_list_detail", list_id=campaign.pk)

    return render(
        request,
        "imports/import_detail.html",
        {
            "batch": batch,
            "issues": batch.issues.all(),
            "replacement_form": form,
        },
    )


def _template_for(batch):
    """Reuse the template from the campaign the failed batch was meant for.

    A failed batch never produced a campaign, so fall back to the most recent
    approved template matching its purpose.
    """
    from django.db.models import Q
    from messaging.models import MessageTemplate

    return (
        MessageTemplate.objects.for_organization(batch.organization)
        .filter(is_active=True)
        .filter(Q(purpose=batch.purpose) | Q(purpose=MessageTemplate.Purpose.GENERAL))
        .filter(
            Q(current_revision__approval_status=MessageTemplate.ApprovalStatus.APPROVED)
            | Q(
                current_revision__isnull=True,
                approval_status=MessageTemplate.ApprovalStatus.APPROVED,
            )
        )
        .order_by("-updated_at")
        .first()
    )
