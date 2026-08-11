from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from account.models import OrganizationSubscription
from campaigns.models import Campaign, CampaignItem
from directory.models import Contact, Doctor
from messaging.models import CampaignMessage, MessageTemplate


def home(request):
    if not request.user.is_authenticated or not request.user.organization_id:
        return render(request, "pages/home.html")

    organization = request.user.organization
    campaigns = Campaign.objects.for_organization(organization)
    messages = CampaignMessage.objects.for_organization(organization)
    today = timezone.localdate()
    recent_campaigns = campaigns.annotate(
        item_count=Count("items", distinct=True),
        sent_count=Count(
            "items__message",
            filter=Q(items__message__status=CampaignMessage.Status.SENT),
            distinct=True,
        ),
    )[:5]
    subscription = OrganizationSubscription.objects.filter(
        organization=organization
    ).select_related("plan").first()

    return render(
        request,
        "pages/home.html",
        {
            "dashboard": {
                "campaigns": campaigns.count(),
                "messages": messages.count(),
                "sent": messages.filter(status=CampaignMessage.Status.SENT).count(),
                "upcoming": CampaignItem.objects.for_organization(organization).filter(
                    appointment_date__gte=today
                ).count(),
                "contacts": Contact.objects.for_organization(organization).count(),
                "doctors": Doctor.objects.for_organization(organization).filter(
                    is_active=True
                ).count(),
                "templates": MessageTemplate.objects.for_organization(organization).filter(
                    approval_status=MessageTemplate.ApprovalStatus.APPROVED,
                    is_active=True,
                ).count(),
                "pending_templates": MessageTemplate.objects.for_organization(
                    organization
                ).filter(
                    approval_status__in=(
                        MessageTemplate.ApprovalStatus.DRAFT,
                        MessageTemplate.ApprovalStatus.PENDING,
                    )
                ).count(),
                "today": CampaignItem.objects.for_organization(organization).filter(
                    appointment_date=today
                ).count(),
                "confirmed_today": CampaignItem.objects.for_organization(organization).filter(
                    appointment_date=today,
                    appointment_status=CampaignItem.AppointmentStatus.CONFIRMED,
                ).count(),
            },
            "recent_campaigns": recent_campaigns,
            "subscription": subscription,
        },
    )
