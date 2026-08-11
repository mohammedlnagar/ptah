import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from appointments.services import change_appointment_status
from campaigns.models import Campaign, CampaignItem, DoctorSummary
from directory.models import Contact
from messaging.models import CampaignMessage, MessageHandoffEvent, MessageTemplate
from messaging.services import (
    record_message_content_edit,
    transition_message_status,
)

from .forms import CampaignUploadForm, MessageTemplateForm
from .utilities.csv_handler import CsvImportError, save_campaign_from_csv


def _tenant_or_403(request):
    if not request.user.organization_id:
        raise PermissionDenied("Your account is not assigned to an organization.")
    if not request.user.organization.is_active:
        raise PermissionDenied("Your organization is inactive.")
    return request.user.organization


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

        if form_type == "message_template":
            if not request.user.has_perm("messaging.add_messagetemplate"):
                raise PermissionDenied("You cannot create message templates.")
            form = MessageTemplateForm(request.POST, user=request.user)
            if form.is_valid():
                template = form.save()
                return JsonResponse(
                    {
                        "success": True,
                        "template_id": template.pk,
                        "message": "Template saved as a draft.",
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
            "message_template_form": MessageTemplateForm(user=request.user),
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
            },
            "doctor_summaries": doctor_summaries,
            "doctor_summary_records": campaign.doctor_summaries.select_related(
                "doctor"
            ).order_by("doctor__name"),
        },
    )


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
    transition_message_status(
        message=campaign_message,
        user=request.user,
        new_status=CampaignMessage.Status.OPENED,
        event_type=MessageHandoffEvent.EventType.WHATSAPP_OPENED,
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
