from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from account.models import CustomUser, Organization
from appointments.models import Appointment, AppointmentStatusEvent
from campaigns.models import Campaign, CampaignItem, DoctorSummary
from directory.models import Doctor
from imports.models import ImportBatch, ImportIssue
from messaging.models import (
    CampaignMessage,
    MessageHandoffEvent,
    MessageTemplate,
    MessageTemplateRevision,
)


class Command(BaseCommand):
    help = "Fail when tenant-owned records reference data from another organization."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample-limit",
            type=int,
            default=10,
            help="Maximum number of primary keys to show for each violation type.",
        )

    def handle(self, *args, **options):
        sample_limit = max(options["sample_limit"], 1)
        checks = [
            (
                "employee.organization",
                CustomUser.objects.filter(organization__isnull=True, is_superuser=False),
            ),
            (
                "organization.subscription",
                Organization.objects.filter(subscription__isnull=True),
            ),
            (
                "doctor.department",
                Doctor.objects.filter(department__isnull=False).exclude(
                    organization_id=F("department__organization_id")
                ),
            ),
            (
                "message_template.created_by",
                MessageTemplate.objects.exclude(
                    organization_id=F("created_by__organization_id")
                ),
            ),
            (
                "message_template.approved_by",
                MessageTemplate.objects.filter(approved_by__isnull=False).exclude(
                    organization_id=F("approved_by__organization_id")
                ),
            ),
            (
                "import_batch.uploaded_by",
                ImportBatch.objects.exclude(
                    organization_id=F("uploaded_by__organization_id")
                ),
            ),
            (
                "import_batch.replaces",
                ImportBatch.objects.filter(replaces__isnull=False).exclude(
                    organization_id=F("replaces__organization_id")
                ),
            ),
            (
                "campaign.created_by",
                Campaign.objects.exclude(
                    organization_id=F("created_by__organization_id")
                ),
            ),
            (
                "campaign.template",
                Campaign.objects.filter(template__isnull=False).exclude(
                    organization_id=F("template__organization_id")
                ),
            ),
            (
                "campaign.import_batch",
                Campaign.objects.filter(import_batch__isnull=False).exclude(
                    organization_id=F("import_batch__organization_id")
                ),
            ),
            (
                "campaign_item.campaign",
                CampaignItem.objects.exclude(
                    organization_id=F("campaign__organization_id")
                ),
            ),
            (
                "campaign_item.contact",
                CampaignItem.objects.exclude(
                    organization_id=F("contact__organization_id")
                ),
            ),
            (
                "campaign_item.doctor",
                CampaignItem.objects.filter(doctor__isnull=False).exclude(
                    organization_id=F("doctor__organization_id")
                ),
            ),
            (
                "message_template.current_revision",
                MessageTemplate.objects.filter(
                    current_revision__isnull=False
                ).exclude(organization_id=F("current_revision__organization_id")),
            ),
            (
                "message_template.current_revision.template",
                MessageTemplate.objects.filter(
                    current_revision__isnull=False
                ).exclude(pk=F("current_revision__template_id")),
            ),
            (
                "import_issue.batch",
                ImportIssue.objects.exclude(
                    organization_id=F("batch__organization_id")
                ),
            ),
            (
                "campaign.template_revision",
                Campaign.objects.filter(template_revision__isnull=False).exclude(
                    organization_id=F("template_revision__organization_id")
                ),
            ),
            (
                "campaign.template_revision.template",
                Campaign.objects.filter(template_revision__isnull=False).exclude(
                    template_id=F("template_revision__template_id")
                ),
            ),
            (
                "campaign_item.appointment",
                CampaignItem.objects.filter(appointment__isnull=False).exclude(
                    organization_id=F("appointment__organization_id")
                ),
            ),
            (
                "campaign_item.appointment.contact",
                CampaignItem.objects.filter(appointment__isnull=False).exclude(
                    contact_id=F("appointment__contact_id")
                ),
            ),
            (
                "appointment.contact",
                Appointment.objects.exclude(
                    organization_id=F("contact__organization_id")
                ),
            ),
            (
                "appointment.doctor",
                Appointment.objects.filter(doctor__isnull=False).exclude(
                    organization_id=F("doctor__organization_id")
                ),
            ),
            (
                "appointment.source_import",
                Appointment.objects.filter(source_import__isnull=False).exclude(
                    organization_id=F("source_import__organization_id")
                ),
            ),
            (
                "appointment_status_event.appointment",
                AppointmentStatusEvent.objects.exclude(
                    organization_id=F("appointment__organization_id")
                ),
            ),
            (
                "appointment_status_event.changed_by",
                AppointmentStatusEvent.objects.exclude(
                    organization_id=F("changed_by__organization_id")
                ),
            ),
            (
                "campaign_message.campaign_item",
                CampaignMessage.objects.exclude(
                    organization_id=F("campaign_item__organization_id")
                ),
            ),
            (
                "campaign_message.template",
                CampaignMessage.objects.filter(template__isnull=False).exclude(
                    organization_id=F("template__organization_id")
                ),
            ),
            (
                "campaign_message.template_revision",
                CampaignMessage.objects.filter(
                    template_revision__isnull=False
                ).exclude(
                    organization_id=F("template_revision__organization_id")
                ),
            ),
            (
                "campaign_message.template_revision.template",
                CampaignMessage.objects.filter(
                    template_revision__isnull=False
                ).exclude(template_id=F("template_revision__template_id")),
            ),
            (
                "campaign_message.sent_by",
                CampaignMessage.objects.filter(sent_by__isnull=False).exclude(
                    organization_id=F("sent_by__organization_id")
                ),
            ),
            (
                "template_revision.template",
                MessageTemplateRevision.objects.exclude(
                    organization_id=F("template__organization_id")
                ),
            ),
            (
                "template_revision.created_by",
                MessageTemplateRevision.objects.exclude(
                    organization_id=F("created_by__organization_id")
                ),
            ),
            (
                "template_revision.approved_by",
                MessageTemplateRevision.objects.filter(
                    approved_by__isnull=False
                ).exclude(organization_id=F("approved_by__organization_id")),
            ),
            (
                "handoff_event.message",
                MessageHandoffEvent.objects.exclude(
                    organization_id=F("message__organization_id")
                ),
            ),
            (
                "handoff_event.actor",
                MessageHandoffEvent.objects.exclude(
                    organization_id=F("actor__organization_id")
                ),
            ),
            (
                "doctor_summary.campaign",
                DoctorSummary.objects.exclude(
                    organization_id=F("campaign__organization_id")
                ),
            ),
            (
                "doctor_summary.doctor",
                DoctorSummary.objects.exclude(
                    organization_id=F("doctor__organization_id")
                ),
            ),
            (
                "doctor_summary.sent_by",
                DoctorSummary.objects.filter(sent_by__isnull=False).exclude(
                    organization_id=F("sent_by__organization_id")
                ),
            ),
        ]

        total = 0
        for label, queryset in checks:
            count = queryset.count()
            if not count:
                continue
            total += count
            sample = list(
                queryset.order_by("pk").values_list("pk", flat=True)[:sample_limit]
            )
            self.stderr.write(
                self.style.ERROR(f"{label}: {count} violation(s); sample PKs: {sample}")
            )

        if total:
            raise CommandError(f"{total} tenant integrity violation(s) detected.")

        self.stdout.write(self.style.SUCCESS("No tenant integrity violations detected."))
