"""Tests for CSV parsing tolerance and the cancelled-appointment guard."""

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from account.models import CustomUser, Organization
from campaigns.models import Campaign, CampaignItem
from imports.models import ImportBatch, ImportIssue
from messaging.models import (
    CampaignMessage,
    MessageHandoffEvent,
    MessageTemplate,
)
from rasel.utilities.csv_handler import (
    CsvImportError,
    clean_csv_data,
    save_campaign_from_csv,
)


HEADER = (
    "Patient Name,Patient Mobile,MR No.,Appointment Date/Time,"
    "Consultant,Doctor Department,Appointment Status,Remarks"
)


def upload(name, body):
    return SimpleUploadedFile(name, body.encode(), content_type="text/csv")


class CleanCsvDataTests(TestCase):
    def test_reads_a_plain_file_whose_first_row_is_the_header(self):
        frame = clean_csv_data(
            upload(
                "plain.csv",
                f"{HEADER}\nMona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n",
            ),
            Campaign.Purpose.APPOINTMENT,
        )

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["Patient Name"], "Mona")

    def test_skips_a_title_block_above_the_header(self):
        body = (
            "Al Noor Hospital,,,,,,,\n"
            "Appointment report 11-08-2026,,,,,,,\n"
            ",,,,,,,\n"
            f"{HEADER}\n"
            "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n"
        )

        frame = clean_csv_data(upload("titled.csv", body), Campaign.Purpose.APPOINTMENT)

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["Patient Name"], "Mona")

    def test_drops_a_trailing_summary_row(self):
        body = (
            f"{HEADER}\n"
            "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n"
            "Total: 1 appointment,,,,,,,\n"
        )

        frame = clean_csv_data(upload("footer.csv", body), Campaign.Purpose.APPOINTMENT)

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["Patient Name"], "Mona")

    def test_keeps_the_physical_line_number_as_the_index(self):
        body = (
            "Al Noor Hospital,,,,,,,\n"
            f"{HEADER}\n"
            "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n"
        )

        frame = clean_csv_data(upload("titled.csv", body), Campaign.Purpose.APPOINTMENT)

        # Title on line 1, header on line 2, so the only data row is line 3
        # which is index 2 zero-based.
        self.assertEqual(list(frame.index), [2])

    def test_missing_required_columns_are_named(self):
        with self.assertRaises(CsvImportError) as context:
            clean_csv_data(
                upload("bad.csv", "Patient Name,Patient Mobile\nMona,+971500000003\n"),
                Campaign.Purpose.APPOINTMENT,
            )

        message = str(context.exception)
        self.assertIn("Appointment Date/Time", message)
        self.assertIn("Consultant", message)

    def test_marketing_uploads_only_need_name_and_mobile(self):
        frame = clean_csv_data(
            upload("marketing.csv", "Patient Name,Patient Mobile\nMona,+971500000003\n"),
            Campaign.Purpose.MARKETING,
        )

        self.assertEqual(len(frame), 1)

    def test_a_file_with_only_a_header_is_rejected(self):
        with self.assertRaises(CsvImportError):
            clean_csv_data(upload("empty.csv", f"{HEADER}\n"), Campaign.Purpose.APPOINTMENT)


class ImportRowNumberTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="clinic-rows"
        )
        self.user = CustomUser.objects.create_user(
            username="operator",
            email="operator@example.com",
            organization=self.organization,
            password="test-password",
        )
        self.template = MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.user,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )

    def test_error_rows_point_at_the_real_spreadsheet_line(self):
        body = (
            "Al Noor Hospital,,,,,,,\n"
            f"{HEADER}\n"
            "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n"
            "Bad,123,MR-2,11-08-2026 10:00,Dr Ali,Dental,Confirmed,\n"
        )

        with self.assertRaises(CsvImportError):
            save_campaign_from_csv(
                user=self.user,
                file=upload("titled.csv", body),
                title="August",
                template=self.template,
                purpose=Campaign.Purpose.APPOINTMENT,
            )

        batch = ImportBatch.objects.get(original_filename="titled.csv")
        issue = ImportIssue.objects.get(batch=batch)
        # The invalid phone number sits on line 4 of the file.
        self.assertEqual(issue.row_number, 4)
        self.assertEqual(issue.column, "Patient Mobile")

    def test_a_messy_export_still_imports_every_valid_row(self):
        body = (
            "Al Noor Hospital,,,,,,,\n"
            "Appointment report,,,,,,,\n"
            f"{HEADER}\n"
            "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n"
            "Sara,+971500000004,MR-2,11-08-2026 10:00,Dr Ali,Dental,Booked,\n"
            "Total: 2 appointments,,,,,,,\n"
        )

        campaign = save_campaign_from_csv(
            user=self.user,
            file=upload("messy.csv", body),
            title="August",
            template=self.template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )

        self.assertEqual(campaign.items.count(), 2)
        self.assertEqual(
            ImportBatch.objects.get(original_filename="messy.csv").status,
            ImportBatch.Status.IMPORTED,
        )


class CancelledAppointmentImportTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="clinic-cancelled"
        )
        self.user = CustomUser.objects.create_user(
            username="operator",
            email="operator@example.com",
            organization=self.organization,
            password="test-password",
        )
        self.template = MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.user,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )

    def test_cancelled_rows_are_imported_and_still_get_a_message(self):
        # Cancelled appointments stay in the dataset for reporting and
        # clinician analysis; the send-time guard lives in the view.
        body = (
            f"{HEADER}\n"
            "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Cancelled,\n"
        )

        campaign = save_campaign_from_csv(
            user=self.user,
            file=upload("cancelled.csv", body),
            title="August",
            template=self.template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )

        item = campaign.items.get()
        self.assertEqual(
            item.appointment_status, CampaignItem.AppointmentStatus.CANCELLED
        )
        self.assertIsNotNone(item.reminder_message)
        self.assertEqual(campaign.summary["appointments"]["cancelled"], 1)


class CancelledWhatsappGuardTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="clinic-guard"
        )
        self.user = CustomUser.objects.create_user(
            username="operator",
            email="operator@example.com",
            organization=self.organization,
            password="test-password",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="messaging",
                codename="change_campaignmessage",
            )
        )
        self.template = MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.user,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.user)

    def _import(self, status):
        body = (
            f"{HEADER}\n"
            f"Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,{status},\n"
        )
        campaign = save_campaign_from_csv(
            user=self.user,
            file=upload(f"{status}.csv", body),
            title="August",
            template=self.template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )
        return campaign.items.get().reminder_message

    def test_booked_appointments_open_whatsapp_directly(self):
        message = self._import("Booked")

        response = self.client.get(
            reverse("open_whatsapp_message", args=[message.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("wa.me", response["Location"])
        message.refresh_from_db()
        self.assertEqual(message.status, CampaignMessage.Status.OPENED)

    def test_cancelled_appointments_show_a_confirmation_first(self):
        message = self._import("Cancelled")

        response = self.client.get(
            reverse("open_whatsapp_message", args=[message.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rasel/confirm_cancelled_message.html")

    def test_the_unconfirmed_request_changes_nothing(self):
        message = self._import("Cancelled")

        self.client.get(reverse("open_whatsapp_message", args=[message.pk]))

        message.refresh_from_db()
        self.assertEqual(message.status, CampaignMessage.Status.PENDING)
        self.assertFalse(MessageHandoffEvent.objects.filter(message=message).exists())

    def test_confirming_opens_whatsapp_and_records_the_override(self):
        message = self._import("Cancelled")

        response = self.client.get(
            reverse("open_whatsapp_message", args=[message.pk]),
            {"confirm_cancelled": "1"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("wa.me", response["Location"])
        message.refresh_from_db()
        self.assertEqual(message.status, CampaignMessage.Status.OPENED)
        event = MessageHandoffEvent.objects.get(
            message=message,
            event_type=MessageHandoffEvent.EventType.WHATSAPP_OPENED,
        )
        self.assertTrue(event.metadata.get("cancelled_override_confirmed"))

    def test_non_cancelled_handoffs_do_not_record_an_override(self):
        message = self._import("Booked")

        self.client.get(reverse("open_whatsapp_message", args=[message.pk]))

        event = MessageHandoffEvent.objects.get(
            message=message,
            event_type=MessageHandoffEvent.EventType.WHATSAPP_OPENED,
        )
        self.assertEqual(event.metadata, {})
