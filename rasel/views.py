import csv
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from account.services import check_campaign_available
from appointments.services import change_appointment_status
from campaigns.models import Campaign, CampaignItem, DoctorSummary
from common.access import tenant_or_403
from messaging.formatting import display_name
from directory.models import Contact
from messaging.models import CampaignMessage, MessageHandoffEvent, MessageTemplate
from messaging.services import (
    record_message_content_edit,
    transition_message_status,
)

from .forms import CampaignUploadForm
from .utilities.csv_handler import CsvImportError, save_campaign_from_csv


_tenant_or_403 = tenant_or_403


@login_required
@permission_required("campaigns.view_campaign", raise_exception=True)
def manage_appointments_and_messages(request):
    organization = _tenant_or_403(request)
    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "appointments_list":
            if not request.user.has_perm("campaigns.add_campaign"):
                raise PermissionDenied("You cannot create campaigns.")
            form = CampaignUploadForm(request.POST, request.FILES, user=request.user)
            if form.is_valid():
                try:
                    check_campaign_available(organization)
                except ValidationError as exc:
                    return JsonResponse(
                        {"success": False, "message": "; ".join(exc.messages)},
                        status=400,
                    )
                try:
                    campaign = save_campaign_from_csv(
                        user=request.user,
                        file=form.cleaned_data["csv_file"],
                        title=form.cleaned_data["title"],
                        template=form.cleaned_data["template"],
                        purpose=form.cleaned_data["purpose"],
                    )
                except CsvImportError as exc:
                    return JsonResponse({"success": False, "message": str(exc)}, status=400)
                messages.success(request, "Campaign created successfully.")
                return JsonResponse(
                    {
                        "success": True,
                        "campaign_id": campaign.pk,
                        "message": "Campaign created successfully.",
                    }
                )
            return JsonResponse({"success": False, "errors": form.errors.get_json_data()}, status=400)

    campaigns = Campaign.objects.for_organization(organization).select_related("template").annotate(
        item_count=Count("items", distinct=True),
        sent_count=Count(
            "items__message",
            filter=Q(items__message__status=CampaignMessage.Status.SENT),
            distinct=True,
        ),
    )
    templates = MessageTemplate.objects.for_organization(organization)
    campaign_messages = CampaignMessage.objects.for_organization(organization)
    return render(
        request,
        "rasel/contact_lists.html",
        {
            "appointments_list_form": CampaignUploadForm(user=request.user),
            "appointment_lists": campaigns,
            "message_templates": templates,
            "campaign_stats": {
                "campaigns": campaigns.count(),
                "messages": campaign_messages.count(),
                "sent": campaign_messages.filter(status=CampaignMessage.Status.SENT).count(),
                "templates": templates.filter(
                    approval_status=MessageTemplate.ApprovalStatus.APPROVED,
                    is_active=True,
                ).count(),
            },
        },
    )


@login_required
@permission_required("campaigns.view_campaign", raise_exception=True)
def appointment_list_detail(request, list_id):
    organization = _tenant_or_403(request)
    campaign = get_object_or_404(
        Campaign.objects.for_organization(organization).select_related("template"), pk=list_id
    )
    all_campaign_messages = CampaignMessage.objects.for_organization(organization).filter(
        campaign_item__campaign=campaign
    )
    campaign_messages = _filtered_messages(request, campaign)
    # Chips carry their own counts, so the operator can see where the work is
    # before filtering rather than after.
    doctor_counts = (
        campaign.items.exclude(doctor_name_snapshot="")
        .values("doctor_name_snapshot")
        .annotate(total=Count("id"))
        .order_by("doctor_name_snapshot")
    )
    doctors = campaign.items.order_by("doctor_name_snapshot").values_list(
        "doctor_name_snapshot", flat=True
    ).distinct()
    doctor_summaries = campaign.items.exclude(doctor_name_snapshot="").values(
        "doctor_name_snapshot", "department_name_snapshot"
    ).annotate(
        total=Count("id"),
        confirmed=Count(
            "id", filter=Q(appointment_status=CampaignItem.AppointmentStatus.CONFIRMED)
        ),
        cancelled=Count(
            "id", filter=Q(appointment_status=CampaignItem.AppointmentStatus.CANCELLED)
        ),
    ).order_by("doctor_name_snapshot")
    return render(
        request,
        "rasel/list_detail.html",
        {
            "appointment_list": campaign,
            "assigned_messages": campaign_messages,
            "doctors": doctors,
            "doctor_counts": doctor_counts,
            "result_count": campaign_messages.count(),
            "message_metrics": {
                "total": all_campaign_messages.count(),
                "pending": all_campaign_messages.filter(
                    status=CampaignMessage.Status.PENDING
                ).count(),
                "opened": all_campaign_messages.filter(
                    status=CampaignMessage.Status.OPENED
                ).count(),
                "sent": all_campaign_messages.filter(
                    status=CampaignMessage.Status.SENT
                ).count(),
                "skipped": all_campaign_messages.filter(
                    status=CampaignMessage.Status.SKIPPED
                ).count(),
            },
            "doctor_summaries": doctor_summaries,
            # The WhatsApp message condenses long lists, but the operator on
            # this screen always sees every appointment.
            "doctor_summary_records": _doctor_summaries_with_appointments(campaign),
        },
    )


def _doctor_summaries_with_appointments(campaign):
    """Each doctor's summary paired with every appointment behind it."""
    grouped = {}
    items = campaign.items.filter(doctor__isnull=False).order_by(
        "appointment_date", "appointment_time", "row_number"
    )
    for item in items:
        grouped.setdefault(item.doctor_id, []).append(item)
    summaries = campaign.doctor_summaries.select_related(
        "doctor", "doctor__department"
    ).order_by("doctor__name")
    return [
        {
            "summary": summary,
            "appointments": [
                # Tidied the same way as the message, so screen and WhatsApp
                # show a patient's name identically.
                {"item": item, "name": display_name(item.patient_name_snapshot)}
                for item in grouped.get(summary.doctor_id, [])
            ],
        }
        for summary in summaries
    ]


@login_required
@permission_required("campaigns.change_campaign", raise_exception=True)
@require_POST
def update_campaign_retention(request, list_id):
    organization = _tenant_or_403(request)
    campaign = get_object_or_404(
        Campaign.objects.for_organization(organization), pk=list_id
    )
    if campaign.is_scrubbed:
        messages.error(
            request, "Patient details have already been removed from this list."
        )
        return redirect("appointment_list_detail", list_id=campaign.pk)

    if request.POST.get("action") == "never":
        campaign.scrub_after = None
        campaign.save(update_fields=("scrub_after", "updated_at"))
        messages.success(
            request, "Patient details will be kept on this list indefinitely."
        )
        return redirect("appointment_list_detail", list_id=campaign.pk)

    raw_days = (request.POST.get("retain_days") or "").strip()
    try:
        days = int(raw_days)
    except ValueError:
        messages.error(request, "Enter a whole number of days.")
        return redirect("appointment_list_detail", list_id=campaign.pk)
    if days < 0:
        messages.error(request, "Enter zero or more days.")
        return redirect("appointment_list_detail", list_id=campaign.pk)

    # Counted from the upload, so "2 days" means the same thing whenever it is
    # set; a past date simply makes the list due at the next scheduled run.
    campaign.scrub_after = campaign.created_at + datetime.timedelta(days=days)
    campaign.save(update_fields=("scrub_after", "updated_at"))
    # localtime, so the flash agrees with the date the template renders.
    shown = timezone.localtime(campaign.scrub_after)
    messages.success(
        request,
        f"Patient details will be removed on {shown:%d %b %Y at %H:%M}.",
    )
    return redirect("appointment_list_detail", list_id=campaign.pk)


@login_required
@permission_required("messaging.change_campaignmessage", raise_exception=True)
@require_POST
def edit_assigned_message(request):
    organization = _tenant_or_403(request)
    campaign_message = get_object_or_404(
        CampaignMessage.objects.for_organization(organization), pk=request.POST.get("message_id")
    )
    rendered_content = request.POST.get("new_message", "").strip()
    if not rendered_content:
        return JsonResponse({"success": False, "message": "Message cannot be empty."}, status=400)
    record_message_content_edit(
        message=campaign_message,
        user=request.user,
        rendered_content=rendered_content,
    )
    return JsonResponse({"success": True})


@login_required
@permission_required("messaging.change_campaignmessage", raise_exception=True)
@require_POST
def update_assigned_message_status(request):
    organization = _tenant_or_403(request)
    campaign_message = get_object_or_404(
        CampaignMessage.objects.for_organization(organization), pk=request.POST.get("message_id")
    )
    new_status = request.POST.get("status")
    if new_status not in CampaignMessage.Status.values:
        return JsonResponse({"success": False, "message": "Invalid message status."}, status=400)
    transition_message_status(
        message=campaign_message,
        user=request.user,
        new_status=new_status,
    )
    return JsonResponse({"success": True})


@login_required
@permission_required("messaging.change_campaignmessage", raise_exception=True)
@require_GET
def open_whatsapp_message(request, message_id):
    organization = _tenant_or_403(request)
    campaign_message = get_object_or_404(
        CampaignMessage.objects.for_organization(organization).select_related(
            "organization", "campaign_item"
        ),
        pk=message_id,
    )
    item = campaign_message.campaign_item
    is_cancelled = (
        item.appointment_status == CampaignItem.AppointmentStatus.CANCELLED
    )
    override_confirmed = request.GET.get("confirm_cancelled") == "1"
    if is_cancelled and not override_confirmed:
        # Sending a reminder for a cancelled appointment is usually a mistake,
        # so the operator has to opt in before the handoff is recorded.
        return render(
            request,
            "rasel/confirm_cancelled_message.html",
            {"campaign_message": campaign_message, "item": item},
        )
    transition_message_status(
        message=campaign_message,
        user=request.user,
        new_status=CampaignMessage.Status.OPENED,
        event_type=MessageHandoffEvent.EventType.WHATSAPP_OPENED,
        metadata={"cancelled_override_confirmed": True} if is_cancelled else None,
    )
    return redirect(campaign_message.whatsapp_url())


@login_required
@permission_required("campaigns.change_doctorsummary", raise_exception=True)
@require_GET
def open_doctor_summary(request, summary_id):
    organization = _tenant_or_403(request)
    doctor_summary = get_object_or_404(
        DoctorSummary.objects.for_organization(organization).select_related(
            "organization", "doctor"
        ),
        pk=summary_id,
    )
    destination = doctor_summary.whatsapp_url()
    if not destination:
        return JsonResponse(
            {"success": False, "message": "Add the doctor's phone number first."},
            status=400,
        )
    if doctor_summary.status != DoctorSummary.Status.SENT:
        doctor_summary.status = DoctorSummary.Status.OPENED
    doctor_summary.opened_at = timezone.now()
    doctor_summary.save(update_fields=("status", "opened_at", "updated_at"))
    return redirect(destination)


def _filtered_messages(request, campaign):
    query = CampaignMessage.objects.for_organization(campaign.organization).filter(
        campaign_item__campaign=campaign
    )
    filters = {
        "doctor": "campaign_item__doctor_name_snapshot__icontains",
        "department": "campaign_item__department_name_snapshot__icontains",
        "name": "campaign_item__patient_name_snapshot__icontains",
        "mrn": "campaign_item__mrn_snapshot__icontains",
        "phone": "campaign_item__phone_number_snapshot__icontains",
        "date": "campaign_item__appointment_date",
        "time": "campaign_item__appointment_time",
        "appointment_status": "campaign_item__appointment_status",
        "message_status": "status",
    }
    for parameter, lookup in filters.items():
        value = request.GET.get(parameter, "").strip()
        if value:
            query = query.filter(**{lookup: value})
    search = request.GET.get("q", "").strip()
    if search:
        query = query.filter(
            Q(campaign_item__patient_name_snapshot__icontains=search)
            | Q(campaign_item__phone_number_snapshot__icontains=search)
            | Q(campaign_item__mrn_snapshot__icontains=search)
            | Q(campaign_item__doctor_name_snapshot__icontains=search)
            | Q(campaign_item__department_name_snapshot__icontains=search)
        )
    return query.select_related("campaign_item")


@login_required
@permission_required("campaigns.view_campaign", raise_exception=True)
@require_GET
def filter_assigned_messages(request, list_id):
    organization = _tenant_or_403(request)
    campaign = get_object_or_404(Campaign.objects.for_organization(organization), pk=list_id)
    data = []
    for campaign_message in _filtered_messages(request, campaign)[:500]:
        item = campaign_message.campaign_item
        data.append(
            {
                "id": campaign_message.pk,
                "patient_name": item.patient_name_snapshot,
                "phone_number": item.phone_number_snapshot,
                "mrn": item.mrn_snapshot,
                "doctor_name": item.doctor_name_snapshot,
                "department": item.department_name_snapshot,
                "appointment_date": item.appointment_date.isoformat() if item.appointment_date else None,
                "appointment_time": item.appointment_time.isoformat() if item.appointment_time else None,
                "appointment_status": item.appointment_status,
                "rendered_content": campaign_message.rendered_content,
                "message_status": campaign_message.status,
            }
        )
    return JsonResponse({"success": True, "data": data})


@login_required
@permission_required("campaigns.view_campaign", raise_exception=True)
@require_GET
def export_assigned_messages_to_csv(request, list_id):
    organization = _tenant_or_403(request)
    campaign = get_object_or_404(Campaign.objects.for_organization(organization), pk=list_id)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="campaign_{campaign.pk}.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Patient Name",
            "Phone",
            "MRN",
            "Doctor",
            "Department",
            "Appointment Date",
            "Appointment Time",
            "Appointment Status",
            "Message",
            "Message Status",
        ]
    )
    for campaign_message in _filtered_messages(request, campaign):
        item = campaign_message.campaign_item
        writer.writerow(
            [
                item.patient_name_snapshot,
                item.phone_number_snapshot,
                item.mrn_snapshot,
                item.doctor_name_snapshot,
                item.department_name_snapshot,
                item.appointment_date or "",
                item.appointment_time or "",
                item.appointment_status or "",
                campaign_message.rendered_content,
                campaign_message.status,
            ]
        )
    return response


@login_required
@permission_required("directory.change_contact", raise_exception=True)
@require_POST
def update_contact_details(request):
    organization = _tenant_or_403(request)
    contact = get_object_or_404(
        Contact.objects.for_organization(organization), pk=request.POST.get("contact_id")
    )
    contact.name = request.POST.get("name", "").strip()
    contact.phone_number = request.POST.get("phone_number", "").strip()
    contact.full_clean()
    contact.save(update_fields=("name", "phone_number", "updated_at"))
    return JsonResponse({"success": True})


@login_required
@permission_required("campaigns.change_campaignitem", raise_exception=True)
@require_POST
def update_appointment_status(request, item_id):
    organization = _tenant_or_403(request)
    item = get_object_or_404(
        CampaignItem.objects.for_organization(organization), pk=item_id
    )
    new_status = request.POST.get("status")
    if new_status not in CampaignItem.AppointmentStatus.values:
        return JsonResponse({"success": False, "message": "Invalid appointment status."}, status=400)
    if not item.appointment_id:
        return JsonResponse(
            {"success": False, "message": "This item has no linked appointment."},
            status=409,
        )
    change_appointment_status(
        appointment=item.appointment,
        user=request.user,
        new_status=new_status,
        reason=request.POST.get("reason", ""),
    )
    item.refresh_from_db(fields=("appointment_status",))
    return JsonResponse({"success": True})


@login_required
@permission_required("campaigns.view_campaign", raise_exception=True)
def send_queue(request):
    """Send queue entry point for the nav, which has no campaign id to hand.

    Sends the operator to the campaign with work left in it — the most recently
    created one still holding pending messages — so "Send queue" resumes rather
    than making them pick from a list first. Falls back to the campaign index
    when nothing is pending.
    """
    organization = _tenant_or_403(request)
    campaign = (
        Campaign.objects.for_organization(organization)
        .filter(items__message__status=CampaignMessage.Status.PENDING)
        .order_by("-created_at")
        .distinct()
        .first()
    )
    if campaign is None:
        campaign = (
            Campaign.objects.for_organization(organization).order_by("-created_at").first()
        )
    if campaign is None:
        messages.info(request, "Create a campaign to start sending.")
        return redirect("manage_appointments")
    return redirect("appointment_list_detail", list_id=campaign.pk)
