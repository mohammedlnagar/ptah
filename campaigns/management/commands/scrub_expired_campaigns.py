from django.core.management.base import BaseCommand

from campaigns.services import due_for_scrub, scrub_campaign


class Command(BaseCommand):
    help = (
        "Remove patient name and phone from lists whose retention window has "
        "closed. Intended to run daily from a scheduled job."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be scrubbed without changing anything.",
        )

    def handle(self, *args, **options):
        due = due_for_scrub().select_related("organization").order_by("scrub_after")
        if not due.exists():
            self.stdout.write("No lists are due for scrubbing.")
            return

        scrubbed_rows = 0
        scrubbed_lists = 0
        for campaign in due:
            label = f"{campaign.organization.slug}/{campaign.title}"
            if options["dry_run"]:
                self.stdout.write(
                    f"Would scrub list {campaign.pk} ({label}), "
                    f"due {campaign.scrub_after:%Y-%m-%d %H:%M}."
                )
                continue
            rows = scrub_campaign(campaign)
            scrubbed_rows += rows
            scrubbed_lists += 1
            self.stdout.write(
                self.style.SUCCESS(f"Scrubbed {rows} row(s) from {label}.")
            )

        if not options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Scrubbed {scrubbed_rows} row(s) across "
                    f"{scrubbed_lists} list(s)."
                )
            )
