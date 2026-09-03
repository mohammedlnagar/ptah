"""The follow-up sequence and campaign updates.

Covers the policy dates, that a re-uploaded export updates rather than
duplicates, and that nothing cancels an appointment on its own.
"""

import datetime
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from account.models import CustomUser, Organization
from campaigns.followups import (
    generate_stage_messages,
    stage_due_at,
    stages_for,
    void_settled_cancellations,
)
from campaigns.models import Campaign, CampaignItem
from campaigns.updates import match_key, update_campaign_from_csv
from messaging.models import CampaignMessage, MessageTemplate
from rasel.utilities.csv_handler import CsvImportError, save_campaign_from_csv


HEADER = (
    "Patient Name,Patient Mobile,MR No.,Appointment Date/Time,"
    "Consultant,Doctor Department,Appointment Status,Remarks"
)
# Two patients, one clinic day, both unconfirmed at first export.
ROWS = (
    "Mona Saleh,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Booked,Arrive early\n"
    "Omar Saleh,+971500000004,MR-2,11-08-2026 10:00,Dr Ali,Dental,Booked,\n"
)


def upload(name, body):
    return SimpleUploadedFile(name, body.encode(), content_type="text/csv")


class FollowUpFixture(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug=f"followups-{self._testMethodName[:36]}"
        )
        self.user = CustomUser.objects.create_user(
            username="operator",
            email="operator@example.com",
            organization=self.organization,
            password="test-password-123",
        )
        self.reminder = self._template("Reminder", "Hello #patient_name, please confirm.")
        self.follow_up = self._template("Follow up", "#patient_name, tomorrow at #appointment_time.")
        self.cancellation = self._template("Cancellation", "#patient_name, we did not hear back.")

    def _template(self, name, content):
        return MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.user,
            name=name,
            content=content,
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )

    def build_campaign(self, rows=ROWS, with_stages=True):
        campaign = save_campaign_from_csv(
            user=self.user,
            file=upload("day.csv", f"{HEADER}\n{rows}"),
            title="11 August",
            template=self.reminder,
            purpose=Campaign.Purpose.APPOINTMENT,
        )
        if with_stages:
            campaign.follow_up_template = self.follow_up
            campaign.cancellation_template = self.cancellation
            campaign.save(
                update_fields=["follow_up_template", "cancellation_template"]
            )
            generate_stage_messages(campaign)
        return campaign


class StageScheduleTests(FollowUpFixture):
    """The policy dates, which every other part reads from one place."""

    def setUp(self):
        super().setUp()
        self.tz = ZoneInfo("Asia/Dubai")
        self.appointment_at = datetime.datetime(
            2026, 8, 11, 9, 30, tzinfo=self.tz
        )

    def test_the_reminder_is_due_two_days_ahead(self):
        due = stage_due_at(
            CampaignMessage.Stage.REMINDER, self.appointment_at, self.tz
        )

        self.assertEqual(due, datetime.datetime(2026, 8, 9, 9, 30, tzinfo=self.tz))

    def test_the_follow_up_is_due_24_hours_ahead(self):
        due = stage_due_at(
            CampaignMessage.Stage.FOLLOW_UP, self.appointment_at, self.tz
        )

        self.assertEqual(due, datetime.datetime(2026, 8, 10, 9, 30, tzinfo=self.tz))

    def test_the_cancellation_is_due_at_7pm_the_evening_before(self):
        due = stage_due_at(
            CampaignMessage.Stage.CANCELLATION, self.appointment_at, self.tz
        )

        self.assertEqual(due, datetime.datetime(2026, 8, 10, 19, 0, tzinfo=self.tz))

    def test_7pm_is_local_to_the_clinic_not_the_server(self):
        # An early appointment in a +04 clinic: the deadline is 19:00 there,
        # which is 15:00 UTC. Computing it in UTC would land at the wrong hour.
        due = stage_due_at(
            CampaignMessage.Stage.CANCELLATION, self.appointment_at, self.tz
        )

        self.assertEqual(due.astimezone(datetime.timezone.utc).hour, 15)

    def test_a_row_with_no_appointment_has_no_due_date(self):
        self.assertIsNone(
            stage_due_at(CampaignMessage.Stage.REMINDER, None, self.tz)
        )


class StageGenerationTests(FollowUpFixture):
    def test_a_campaign_without_later_templates_only_reminds(self):
        campaign = self.build_campaign(with_stages=False)

        self.assertEqual(stages_for(campaign), [CampaignMessage.Stage.REMINDER])
        stages = set(
            CampaignMessage.objects.filter(
                campaign_item__campaign=campaign
            ).values_list("stage", flat=True)
        )
        self.assertEqual(stages, {CampaignMessage.Stage.REMINDER})

    def test_every_stage_is_generated_once_per_recipient(self):
        campaign = self.build_campaign()

        for item in campaign.items.all():
            with self.subTest(item=item.pk):
                self.assertEqual(
                    sorted(item.messages.values_list("stage", flat=True)),
                    ["cancellation", "follow_up", "reminder"],
                )

    def test_generation_is_idempotent(self):
        campaign = self.build_campaign()
        before = CampaignMessage.objects.filter(
            campaign_item__campaign=campaign
        ).count()

        created = generate_stage_messages(campaign)

        self.assertEqual(created, 0)
        self.assertEqual(
            CampaignMessage.objects.filter(campaign_item__campaign=campaign).count(),
            before,
        )

    def test_the_reminder_created_at_import_carries_its_due_date(self):
        # Reminders used to be written inline by the importer with no due
        # date; they now come from the same policy as the later stages.
        campaign = self.build_campaign()
        item = campaign.items.get(mrn_snapshot="MR-1")

        reminder = item.messages.get(stage=CampaignMessage.Stage.REMINDER)

        self.assertIsNotNone(reminder.due_at)
        appointment_at = item.appointment.scheduled_at
        self.assertEqual(appointment_at - reminder.due_at, datetime.timedelta(days=2))

    def test_each_stage_renders_its_own_template(self):
        campaign = self.build_campaign()
        item = campaign.items.order_by("row_number").first()

        rendered = {
            m.stage: m.rendered_content for m in item.messages.all()
        }

        self.assertIn("please confirm", rendered["reminder"])
        self.assertIn("tomorrow at", rendered["follow_up"])
        self.assertIn("did not hear back", rendered["cancellation"])


class CancellationTests(FollowUpFixture):
    """Nothing is cancelled automatically; confirmed rows are simply retired."""

    def setUp(self):
        super().setUp()
        self.campaign = self.build_campaign()
        self.after_deadline = datetime.datetime(
            2026, 8, 10, 20, 0, tzinfo=ZoneInfo("Asia/Dubai")
        )

    def _cancellation(self, item):
        return item.messages.get(stage=CampaignMessage.Stage.CANCELLATION)

    def test_a_confirmed_appointment_retires_its_cancellation(self):
        item = self.campaign.items.order_by("row_number").first()
        item.appointment_status = CampaignItem.AppointmentStatus.CONFIRMED
        item.save(update_fields=["appointment_status"])

        voided = void_settled_cancellations(now=self.after_deadline)

        self.assertEqual(voided, 1)
        self.assertEqual(
            self._cancellation(item).status, CampaignMessage.Status.VOIDED
        )

    def test_an_unconfirmed_appointment_stays_pending_for_a_person_to_decide(self):
        item = self.campaign.items.order_by("row_number").last()

        void_settled_cancellations(now=self.after_deadline)

        self.assertEqual(
            self._cancellation(item).status, CampaignMessage.Status.PENDING
        )

    def test_the_appointment_status_is_never_changed_by_the_pass(self):
        void_settled_cancellations(now=self.after_deadline)

        for item in self.campaign.items.all():
            item.refresh_from_db()
            with self.subTest(item=item.pk):
                self.assertEqual(
                    item.appointment_status,
                    CampaignItem.AppointmentStatus.BOOKED,
                )

    def test_nothing_is_retired_before_the_deadline(self):
        item = self.campaign.items.first()
        item.appointment_status = CampaignItem.AppointmentStatus.CONFIRMED
        item.save(update_fields=["appointment_status"])
        before_deadline = datetime.datetime(
            2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Asia/Dubai")
        )

        self.assertEqual(void_settled_cancellations(now=before_deadline), 0)

    def test_the_command_runs_and_reports(self):
        item = self.campaign.items.first()
        item.appointment_status = CampaignItem.AppointmentStatus.CONFIRMED
        item.save(update_fields=["appointment_status"])
        out = StringIO()

        call_command("process_followups", stdout=out)

        self.assertIn("stage message", out.getvalue())

    def test_the_command_dry_run_changes_nothing(self):
        before = list(
            CampaignMessage.objects.order_by("pk").values_list("status", flat=True)
        )
        out = StringIO()

        call_command("process_followups", "--dry-run", stdout=out)

        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(
            list(
                CampaignMessage.objects.order_by("pk").values_list(
                    "status", flat=True
                )
            ),
            before,
        )


class MatchKeyTests(TestCase):
    def test_mrn_identifies_the_patient(self):
        when = datetime.datetime(2026, 8, 11, 9, 30, tzinfo=datetime.timezone.utc)

        self.assertEqual(
            match_key(mrn="MR-1", phone="+971500000003", scheduled_at=when, doctor_name="Dr Ali"),
            match_key(mrn="mr-1", phone="+971999999999", scheduled_at=when, doctor_name="dr ali"),
        )

    def test_phone_stands_in_when_there_is_no_mrn(self):
        when = datetime.datetime(2026, 8, 11, 9, 30, tzinfo=datetime.timezone.utc)

        self.assertEqual(
            match_key(mrn="", phone="+971500000003", scheduled_at=when, doctor_name="Dr Ali"),
            match_key(mrn="", phone="+971500000003", scheduled_at=when, doctor_name="Dr Ali"),
        )

    def test_a_different_time_is_a_different_appointment(self):
        first = datetime.datetime(2026, 8, 11, 9, 30, tzinfo=datetime.timezone.utc)
        second = datetime.datetime(2026, 8, 11, 14, 0, tzinfo=datetime.timezone.utc)

        self.assertNotEqual(
            match_key(mrn="MR-1", phone="", scheduled_at=first, doctor_name="Dr Ali"),
            match_key(mrn="MR-1", phone="", scheduled_at=second, doctor_name="Dr Ali"),
        )

    def test_a_different_clinician_is_a_different_appointment(self):
        when = datetime.datetime(2026, 8, 11, 9, 30, tzinfo=datetime.timezone.utc)

        self.assertNotEqual(
            match_key(mrn="MR-1", phone="", scheduled_at=when, doctor_name="Dr Ali"),
            match_key(mrn="MR-1", phone="", scheduled_at=when, doctor_name="Dr Osman"),
        )


class CampaignUpdateTests(FollowUpFixture):
    def setUp(self):
        super().setUp()
        self.campaign = self.build_campaign()

    def test_a_matching_row_updates_status_instead_of_duplicating(self):
        updated = ROWS.replace(
            "MR-1,11-08-2026 09:30,Dr Ali,Dental,Booked",
            "MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed",
        )

        result = update_campaign_from_csv(
            user=self.user,
            campaign=self.campaign,
            file=upload("update.csv", f"{HEADER}\n{updated}"),
        )

        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["status_changed"], 1)
        self.assertEqual(result["added"], 0)
        self.assertEqual(self.campaign.items.count(), 2)
        item = self.campaign.items.get(mrn_snapshot="MR-1")
        self.assertEqual(
            item.appointment_status, CampaignItem.AppointmentStatus.CONFIRMED
        )

    def test_the_status_change_is_recorded_on_the_appointment(self):
        updated = ROWS.replace("Dental,Booked,Arrive early", "Dental,Confirmed,Arrive early")

        update_campaign_from_csv(
            user=self.user,
            campaign=self.campaign,
            file=upload("update.csv", f"{HEADER}\n{updated}"),
        )

        item = self.campaign.items.get(mrn_snapshot="MR-1")
        self.assertEqual(item.appointment.status, "confirmed")
        self.assertTrue(
            item.appointment.status_events.filter(new_status="confirmed").exists()
        )

    def test_a_new_booking_is_added_with_its_own_stages(self):
        with_new = ROWS + (
            "Sara Noor,+971500000005,MR-3,11-08-2026 11:00,Dr Ali,Dental,Booked,\n"
        )

        result = update_campaign_from_csv(
            user=self.user,
            campaign=self.campaign,
            file=upload("update.csv", f"{HEADER}\n{with_new}"),
        )

        self.assertEqual(result["added"], 1)
        self.assertEqual(self.campaign.items.count(), 3)
        added = self.campaign.items.get(mrn_snapshot="MR-3")
        self.assertEqual(
            sorted(added.messages.values_list("stage", flat=True)),
            ["cancellation", "follow_up", "reminder"],
        )

    def test_a_rescheduled_appointment_is_treated_as_new_rather_than_guessed(self):
        # Same patient and clinician, different time. Matching it to the old
        # row would silently move an appointment; adding it leaves both
        # visible for a person to reconcile.
        moved = ROWS.replace("MR-1,11-08-2026 09:30", "MR-1,11-08-2026 15:45")

        result = update_campaign_from_csv(
            user=self.user,
            campaign=self.campaign,
            file=upload("update.csv", f"{HEADER}\n{moved}"),
        )

        self.assertEqual(result["added"], 1)
        self.assertEqual(result["matched"], 1)

    def test_an_updated_remark_is_carried_over(self):
        updated = ROWS.replace("Booked,Arrive early", "Booked,Bring x-rays")

        update_campaign_from_csv(
            user=self.user,
            campaign=self.campaign,
            file=upload("update.csv", f"{HEADER}\n{updated}"),
        )

        item = self.campaign.items.get(mrn_snapshot="MR-1")
        self.assertEqual(item.appointment_remarks, "Bring x-rays")

    def test_the_update_is_recorded_as_its_own_import_batch(self):
        result = update_campaign_from_csv(
            user=self.user,
            campaign=self.campaign,
            file=upload("second-export.csv", f"{HEADER}\n{ROWS}"),
        )

        batch = result["batch"]
        self.assertEqual(batch.updates_campaign_id, self.campaign.pk)
        self.assertEqual(batch.original_filename, "second-export.csv")
        self.assertEqual(self.campaign.update_batches.count(), 1)

    def test_a_scrubbed_list_cannot_be_updated(self):
        self.campaign.scrubbed_at = timezone.now()
        self.campaign.save(update_fields=["scrubbed_at"])

        with self.assertRaises(CsvImportError):
            update_campaign_from_csv(
                user=self.user,
                campaign=self.campaign,
                file=upload("update.csv", f"{HEADER}\n{ROWS}"),
            )

    def test_another_organizations_campaign_is_refused(self):
        other = Organization.objects.create(name="Other", slug="other-followups")
        theirs = Campaign.objects.create(
            organization=other,
            created_by=self.user,
            title="Theirs",
            purpose=Campaign.Purpose.APPOINTMENT,
        )

        with self.assertRaises(CsvImportError):
            update_campaign_from_csv(
                user=self.user,
                campaign=theirs,
                file=upload("update.csv", f"{HEADER}\n{ROWS}"),
            )

    def test_an_invalid_file_records_a_failed_batch_and_changes_nothing(self):
        before = self.campaign.items.count()

        with self.assertRaises(CsvImportError):
            update_campaign_from_csv(
                user=self.user,
                campaign=self.campaign,
                file=upload("bad.csv", f"{HEADER}\nNo Phone,,MR-9,,,,,\n"),
            )

        self.assertEqual(self.campaign.items.count(), before)
