"""Retention scrubbing: identity goes, reporting stays."""

import datetime
from io import StringIO

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import CustomUser, Organization
from appointments.models import Appointment
from campaigns.models import Campaign, CampaignItem, DoctorSummary
from campaigns.services import due_for_scrub, row_fingerprint, scrub_campaign
from directory.models import Contact
from imports.models import ImportBatch
from messaging.models import CampaignMessage, MessageTemplate
from rasel.utilities.csv_handler import save_campaign_from_csv


HEADER = (
    "Patient Name,Patient Mobile,MR No.,Appointment Date/Time,"
    "Consultant,Doctor Department,Appointment Status,Remarks"
)
ROWS = (
    "Mona Saleh,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,Arrive early\n"
    "Omar Saleh,+971500000003,MR-2,11-08-2026 10:00,Dr Ali,Dental,Booked,\n"
)


def upload(name, body):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, body.encode(), content_type="text/csv")


class RetentionFixture(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug=f"clinic-{self._testMethodName[:40]}"
        )
        self.user = CustomUser.objects.create_user(
            username="operator",
            email="operator@example.com",
            organization=self.organization,
            password="test-password-123",
        )
        self.template = MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.user,
            name="Reminder",
            content="Hello #patient_name, your appointment is #appointment_status.",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )

    def build_campaign(self, filename="list.csv"):
        return save_campaign_from_csv(
            user=self.user,
            file=upload(filename, f"{HEADER}\n{ROWS}"),
            title="August reminders",
            template=self.template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )


class ScrubScheduleTests(RetentionFixture):
    def test_a_new_list_inherits_the_organization_default(self):
        campaign = self.build_campaign()

        self.assertIsNotNone(campaign.scrub_after)
        expected = campaign.created_at + datetime.timedelta(days=2)
        self.assertAlmostEqual(
            campaign.scrub_after, expected, delta=datetime.timedelta(minutes=1)
        )

    def test_zero_days_means_never(self):
        self.organization.campaign_retention_days = 0
        self.organization.save(update_fields=("campaign_retention_days",))

        campaign = self.build_campaign()

        self.assertIsNone(campaign.scrub_after)

    def test_a_custom_retention_is_honoured(self):
        self.organization.campaign_retention_days = 30
        self.organization.save(update_fields=("campaign_retention_days",))

        campaign = self.build_campaign()

        expected = campaign.created_at + datetime.timedelta(days=30)
        self.assertAlmostEqual(
            campaign.scrub_after, expected, delta=datetime.timedelta(minutes=1)
        )

    def test_due_for_scrub_only_returns_expired_unscrubbed_lists(self):
        overdue = self.build_campaign("overdue.csv")
        overdue.scrub_after = timezone.now() - datetime.timedelta(hours=1)
        overdue.save(update_fields=("scrub_after",))
        future = self.build_campaign("future.csv")
        never = self.build_campaign("never.csv")
        never.scrub_after = None
        never.save(update_fields=("scrub_after",))

        due = list(due_for_scrub())

        self.assertIn(overdue, due)
        self.assertNotIn(future, due)
        self.assertNotIn(never, due)


class ScrubEffectTests(RetentionFixture):
    def setUp(self):
        super().setUp()
        self.campaign = self.build_campaign()
        self.item = self.campaign.items.order_by("row_number").first()
        self.original_raw = dict(self.item.raw_data)

    def test_name_and_phone_are_cleared(self):
        scrub_campaign(self.campaign)

        self.item.refresh_from_db()
        self.assertEqual(self.item.patient_name_snapshot, "")
        self.assertEqual(self.item.phone_number_snapshot, "")

    def test_the_mrn_survives(self):
        scrub_campaign(self.campaign)

        self.item.refresh_from_db()
        self.assertEqual(self.item.mrn_snapshot, "MR-1")

    def test_appointment_details_survive(self):
        scrub_campaign(self.campaign)

        self.item.refresh_from_db()
        self.assertEqual(self.item.doctor_name_snapshot, "Dr Ali")
        self.assertEqual(self.item.department_name_snapshot, "Dental")
        self.assertEqual(self.item.appointment_date, datetime.date(2026, 8, 11))
        self.assertEqual(
            self.item.appointment_status, CampaignItem.AppointmentStatus.CONFIRMED
        )

    def test_the_raw_row_is_replaced_by_its_hash(self):
        scrub_campaign(self.campaign)

        self.item.refresh_from_db()
        self.assertEqual(
            self.item.raw_data, {"sha256": row_fingerprint(self.original_raw)}
        )
        self.assertNotIn("Patient Name", self.item.raw_data)

    def test_the_rendered_message_is_emptied(self):
        self.assertIn("Mona", self.item.message.rendered_content)

        scrub_campaign(self.campaign)

        self.assertEqual(
            CampaignMessage.objects.get(campaign_item=self.item).rendered_content, ""
        )

    def test_the_rows_themselves_are_kept(self):
        before = self.campaign.items.count()

        scrub_campaign(self.campaign)

        self.assertEqual(self.campaign.items.count(), before)

    def test_campaign_summary_and_doctor_summaries_survive(self):
        summary_before = dict(self.campaign.summary)
        self.assertTrue(DoctorSummary.objects.filter(campaign=self.campaign).exists())

        scrub_campaign(self.campaign)

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.summary, summary_before)
        self.assertTrue(DoctorSummary.objects.filter(campaign=self.campaign).exists())

    def test_the_doctor_summary_stops_naming_patients(self):
        # The summary names patients while the list is short, so it has to be
        # rebuilt on scrub or the names would outlive the cleanup.
        summary = DoctorSummary.objects.get(campaign=self.campaign)
        self.assertIn("Mona Saleh", summary.rendered_content)

        scrub_campaign(self.campaign)

        summary.refresh_from_db()
        self.assertNotIn("Mona Saleh", summary.rendered_content)
        self.assertNotIn("Omar Saleh", summary.rendered_content)

    def test_the_rebuilt_doctor_summary_keeps_its_counts(self):
        scrub_campaign(self.campaign)

        summary = DoctorSummary.objects.get(campaign=self.campaign)
        self.assertIn("2 total:", summary.rendered_content)
        self.assertEqual(summary.metrics["total"], 2)

    def test_contacts_and_appointments_are_untouched(self):
        contacts_before = set(
            Contact.objects.for_organization(self.organization).values_list(
                "name", "phone_number"
            )
        )
        appointments_before = Appointment.objects.for_organization(
            self.organization
        ).count()

        scrub_campaign(self.campaign)

        self.assertEqual(
            set(
                Contact.objects.for_organization(self.organization).values_list(
                    "name", "phone_number"
                )
            ),
            contacts_before,
        )
        self.assertEqual(
            Appointment.objects.for_organization(self.organization).count(),
            appointments_before,
        )

    def test_the_import_batch_is_untouched(self):
        scrub_campaign(self.campaign)

        batch = ImportBatch.objects.get(original_filename="list.csv")
        self.assertEqual(batch.status, ImportBatch.Status.IMPORTED)
        self.assertNotEqual(batch.sha256, "")

    def test_scrubbing_is_recorded_and_idempotent(self):
        first = scrub_campaign(self.campaign)
        self.campaign.refresh_from_db()
        stamped_at = self.campaign.scrubbed_at

        second = scrub_campaign(self.campaign)

        self.assertEqual(first, 2)
        self.assertEqual(second, 0)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.scrubbed_at, stamped_at)

    def test_an_already_scrubbed_list_is_not_due_again(self):
        self.campaign.scrub_after = timezone.now() - datetime.timedelta(hours=1)
        self.campaign.save(update_fields=("scrub_after",))
        scrub_campaign(self.campaign)

        self.assertNotIn(self.campaign, due_for_scrub())

    def test_an_empty_list_scrubs_without_error(self):
        empty = Campaign.objects.create(
            organization=self.organization,
            created_by=self.user,
            title="Empty",
            purpose=Campaign.Purpose.MARKETING,
        )

        self.assertEqual(scrub_campaign(empty), 0)


class ScrubCommandTests(RetentionFixture):
    def _run(self, *args):
        out = StringIO()
        call_command("scrub_expired_campaigns", *args, stdout=out)
        return out.getvalue()

    def test_nothing_due_reports_cleanly(self):
        self.build_campaign()

        self.assertIn("No lists are due", self._run())

    def test_a_dry_run_changes_nothing(self):
        campaign = self.build_campaign()
        campaign.scrub_after = timezone.now() - datetime.timedelta(hours=1)
        campaign.save(update_fields=("scrub_after",))

        output = self._run("--dry-run")

        self.assertIn("Would scrub", output)
        campaign.refresh_from_db()
        self.assertIsNone(campaign.scrubbed_at)
        self.assertNotEqual(
            campaign.items.first().patient_name_snapshot, ""
        )

    def test_the_command_scrubs_due_lists(self):
        campaign = self.build_campaign()
        campaign.scrub_after = timezone.now() - datetime.timedelta(hours=1)
        campaign.save(update_fields=("scrub_after",))

        self._run()

        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.scrubbed_at)
        self.assertEqual(campaign.items.first().patient_name_snapshot, "")

    def test_lists_that_are_not_due_are_left_alone(self):
        due = self.build_campaign("due.csv")
        due.scrub_after = timezone.now() - datetime.timedelta(hours=1)
        due.save(update_fields=("scrub_after",))
        safe = self.build_campaign("safe.csv")

        self._run()

        safe.refresh_from_db()
        self.assertIsNone(safe.scrubbed_at)
        self.assertNotEqual(safe.items.first().patient_name_snapshot, "")

    def test_another_organizations_list_is_scrubbed_on_its_own_schedule(self):
        # The command is a platform-wide sweep, so it must handle every tenant
        # without mixing their rows together.
        other_org = Organization.objects.create(name="Other", slug="other-scrub")
        other_user = CustomUser.objects.create_user(
            username="other",
            email="other@example.com",
            organization=other_org,
            password="test-password-123",
        )
        other_template = MessageTemplate.objects.create(
            organization=other_org,
            created_by=other_user,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        theirs = save_campaign_from_csv(
            user=other_user,
            file=upload("theirs.csv", f"{HEADER}\n{ROWS}"),
            title="Theirs",
            template=other_template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )
        mine = self.build_campaign("mine.csv")
        mine.scrub_after = timezone.now() - datetime.timedelta(hours=1)
        mine.save(update_fields=("scrub_after",))

        self._run()

        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertIsNotNone(mine.scrubbed_at)
        self.assertIsNone(theirs.scrubbed_at)
        self.assertNotEqual(theirs.items.first().patient_name_snapshot, "")


class RetentionViewTests(RetentionFixture):
    def setUp(self):
        super().setUp()
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="campaigns", codename="change_campaign"
            ),
            Permission.objects.get(
                content_type__app_label="campaigns", codename="view_campaign"
            ),
        )
        self.campaign = self.build_campaign()
        self.client.force_login(self.user)

    def test_setting_days_moves_the_scrub_date(self):
        response = self.client.post(
            reverse("update_campaign_retention", args=[self.campaign.pk]),
            {"action": "set", "retain_days": "7"},
        )

        self.assertRedirects(
            response, reverse("appointment_list_detail", args=[self.campaign.pk])
        )
        self.campaign.refresh_from_db()
        expected = self.campaign.created_at + datetime.timedelta(days=7)
        self.assertAlmostEqual(
            self.campaign.scrub_after, expected, delta=datetime.timedelta(minutes=1)
        )

    def test_keep_forever_clears_the_date(self):
        self.client.post(
            reverse("update_campaign_retention", args=[self.campaign.pk]),
            {"action": "never"},
        )

        self.campaign.refresh_from_db()
        self.assertIsNone(self.campaign.scrub_after)

    def test_a_non_numeric_value_is_rejected(self):
        original = self.campaign.scrub_after

        self.client.post(
            reverse("update_campaign_retention", args=[self.campaign.pk]),
            {"action": "set", "retain_days": "soon"},
        )

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.scrub_after, original)

    def test_a_negative_value_is_rejected(self):
        original = self.campaign.scrub_after

        self.client.post(
            reverse("update_campaign_retention", args=[self.campaign.pk]),
            {"action": "set", "retain_days": "-3"},
        )

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.scrub_after, original)

    def test_an_already_scrubbed_list_cannot_be_rescheduled(self):
        scrub_campaign(self.campaign)

        self.client.post(
            reverse("update_campaign_retention", args=[self.campaign.pk]),
            {"action": "never"},
        )

        self.campaign.refresh_from_db()
        self.assertIsNotNone(self.campaign.scrub_after)

    def test_a_list_from_another_organization_is_a_404(self):
        other_org = Organization.objects.create(name="Other", slug="other-retention")
        other_user = CustomUser.objects.create_user(
            username="other",
            email="other@example.com",
            organization=other_org,
            password="test-password-123",
        )
        theirs = Campaign.objects.create(
            organization=other_org,
            created_by=other_user,
            title="Theirs",
            purpose=Campaign.Purpose.MARKETING,
        )

        response = self.client.post(
            reverse("update_campaign_retention", args=[theirs.pk]),
            {"action": "never"},
        )

        self.assertEqual(response.status_code, 404)


class RemarksDisplayTests(RetentionFixture):
    """The Remarks column from the source file is shown to the operator.

    Rendered against the real template, so these fail if the markup drops it.
    """

    def setUp(self):
        super().setUp()
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="campaigns", codename="view_campaign"
            ),
            Permission.objects.get(
                content_type__app_label="messaging", codename="change_campaignmessage"
            ),
        )
        self.campaign = self.build_campaign()
        self.client.force_login(self.user)

    def test_the_remark_is_imported_from_the_csv(self):
        item = CampaignItem.objects.get(campaign=self.campaign, row_number=1)

        self.assertEqual(item.appointment_remarks, "Arrive early")

    def test_the_remark_is_shown_on_the_list_screen(self):
        response = self.client.get(
            reverse("appointment_list_detail", args=[self.campaign.pk])
        )

        self.assertContains(response, "Arrive early")

    def test_a_row_without_a_remark_renders_nothing(self):
        item = CampaignItem.objects.get(campaign=self.campaign, row_number=2)
        self.assertEqual(item.appointment_remarks, "")

        response = self.client.get(
            reverse("appointment_list_detail", args=[self.campaign.pk])
        )

        # One remark in the file, so exactly one block on the screen.
        self.assertContains(response, "appointment-remarks", count=1)
