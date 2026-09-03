"""Nightly follow-up pass.

Two jobs, neither of which sends or cancels anything:

* fill in stage messages for campaigns that gained a stage template after
  their first import, so the sequence is complete before it comes due;
* retire cancellation messages the patient has already answered, so what
  remains pending and due is exactly the list of appointments needing a
  human decision.

Run after the retention scrub so a scrubbed list is not repopulated.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from campaigns.followups import generate_stage_messages, void_settled_cancellations
from campaigns.models import Campaign
from messaging.models import CampaignMessage


class Command(BaseCommand):
    help = "Generate due follow-up stages and retire cancellations already answered."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options["dry_run"]

        campaigns = (
            Campaign.objects.filter(scrubbed_at__isnull=True)
            .select_related("organization")
            .order_by("pk")
        )

        generated = 0
        for campaign in campaigns:
            if dry_run:
                continue
            generated += generate_stage_messages(campaign)

        voided = 0 if dry_run else void_settled_cancellations(now=now)

        # Pending, due and unconfirmed: the appointments a person has to decide
        # about. Reported so the run says what it surfaced, not just what it
        # wrote.
        awaiting = CampaignMessage.objects.filter(
            stage=CampaignMessage.Stage.CANCELLATION,
            status=CampaignMessage.Status.PENDING,
            due_at__lte=now,
        ).count()

        if dry_run:
            self.stdout.write(
                f"Dry run: {campaigns.count()} active campaign(s); "
                f"{awaiting} cancellation(s) currently awaiting a decision."
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {generated} stage message(s); "
                f"retired {voided} answered cancellation(s)."
            )
        )
        if awaiting:
            self.stdout.write(
                f"{awaiting} cancellation(s) are due and still unconfirmed - "
                "these need an operator decision."
            )
