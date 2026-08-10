import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import CampaignUploadForm, MessageTemplateForm
from .models import Campaign, CampaignItem, CampaignMessage, Contact, MessageTemplate
from .utilities.csv_handler import CsvImportError, save_campaign_from_csv


def _tenant_or_403(request):
    if not request.user.organization_id:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("Your account is not assigned to an organization.")
    return request.user.organization


@login_required
def manage_appointments_and_messages(request):
    organization = _tenant_or_403(request)
    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "appointments_list":
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
        },
    )


@login_required
@permission_required("rasel.change_campaignmessage", raise_exception=True)
@require_POST
def edit_assigned_message(request):
    organization = _tenant_or_403(request)
    campaign_message = get_object_or_404(
        CampaignMessage.objects.for_organization(organization), pk=request.POST.get("message_id")
    )
    rendered_content = request.POST.get("new_message", "").strip()
    if not rendered_content:
        return JsonResponse({"success": False, "message": "Message cannot be empty."}, status=400)
    campaign_message.rendered_content = rendered_content
    campaign_message.save(update_fields=("rendered_content", "updated_at"))
    return JsonResponse({"success": True})


@login_required
@permission_required("rasel.change_campaignmessage", raise_exception=True)
@require_POST
def update_assigned_message_status(request):
    organization = _tenant_or_403(request)
    campaign_message = get_object_or_404(
        CampaignMessage.objects.for_organization(organization), pk=request.POST.get("message_id")
    )
    new_status = request.POST.get("status")
    if new_status not in CampaignMessage.Status.values:
        return JsonResponse({"success": False, "message": "Invalid message status."}, status=400)
    campaign_message.status = new_status
    update_fields = ["status", "updated_at"]
    if new_status == CampaignMessage.Status.SENT:
        campaign_message.sent_at = timezone.now()
        campaign_message.sent_by = request.user
        update_fields.extend(("sent_at", "sent_by"))
    campaign_message.save(update_fields=update_fields)
    return JsonResponse({"success": True})


@login_required
@permission_required("rasel.change_campaignmessage", raise_exception=True)
@require_GET
def open_whatsapp_message(request, message_id):
    organization = _tenant_or_403(request)
    campaign_message = get_object_or_404(
        CampaignMessage.objects.for_organization(organization).select_related(
            "organization", "campaign_item"
        ),
        pk=message_id,
    )
    campaign_message.status = CampaignMessage.Status.OPENED
    campaign_message.opened_at = timezone.now()
    campaign_message.save(update_fields=("status", "opened_at", "updated_at"))
    return redirect(campaign_message.whatsapp_url())


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
@permission_required("rasel.change_contact", raise_exception=True)
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
@permission_required("rasel.change_campaignitem", raise_exception=True)
@require_POST
def update_appointment_status(request, item_id):
    organization = _tenant_or_403(request)
    item = get_object_or_404(
        CampaignItem.objects.for_organization(organization), pk=item_id
    )
    new_status = request.POST.get("status")
    if new_status not in CampaignItem.AppointmentStatus.values:
        return JsonResponse({"success": False, "message": "Invalid appointment status."}, status=400)
    item.appointment_status = new_status
    item.save(update_fields=("appointment_status", "updated_at"))
    return JsonResponse({"success": True})
