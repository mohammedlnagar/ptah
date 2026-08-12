"""Import history, failure detail, and replacement uploads."""

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from account.models import CustomUser, Organization
from campaigns.models import Campaign
from imports.models import ImportBatch, ImportIssue
from messaging.models import MessageTemplate
from rasel.utilities.csv_handler import CsvImportError, save_campaign_from_csv


HEADER = (
    "Patient Name,Patient Mobile,MR No.,Appointment Date/Time,"
    "Consultant,Doctor Department,Appointment Status,Remarks"
)
GOOD_ROW = "Mona,+971500000003,MR-1,11-08-2026 09:30,Dr Ali,Dental,Confirmed,\n"
BAD_ROW = "Broken,123,MR-2,11-08-2026 10:00,Dr Ali,Dental,Confirmed,\n"


def upload(name, body):
    return SimpleUploadedFile(name, body.encode(), content_type="text/csv")


def member(organization, role, email):
    user = CustomUser.objects.create_user(
        username=email.split("@")[0],
        email=email,
        organization=organization,
        password="test-password-123",
    )
    user.groups.add(Group.objects.get(name=role))
    return user


class ImportVisibilityTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="import-clinic"
        )
        self.owner = member(self.organization, "Owner", "owner@example.com")
        self.template = MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.owner,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.owner)

    def _failed_import(self):
        with self.assertRaises(CsvImportError):
            save_campaign_from_csv(
                user=self.owner,
                file=upload("broken.csv", f"{HEADER}\n{BAD_ROW}"),
                title="Broken",
                template=self.template,
                purpose=Campaign.Purpose.APPOINTMENT,
            )
        return ImportBatch.objects.get(original_filename="broken.csv")

    def test_a_failed_import_is_listed(self):
        batch = self._failed_import()

        response = self.client.get(reverse("import_list"))

        self.assertIn(batch, response.context["batches"])

    def test_imports_from_other_organizations_are_hidden(self):
        other = Organization.objects.create(name="Other", slug="other-import-clinic")
        other_owner = member(other, "Owner", "other@example.com")
        theirs = ImportBatch.objects.create(
            organization=other,
            uploaded_by=other_owner,
            purpose=ImportBatch.Purpose.APPOINTMENT,
            original_filename="theirs.csv",
        )

        response = self.client.get(reverse("import_list"))

        self.assertNotIn(theirs, response.context["batches"])

    def test_the_detail_page_explains_each_problem(self):
        batch = self._failed_import()

        response = self.client.get(reverse("import_detail", args=[batch.pk]))

        issues = list(response.context["issues"])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].column, "Patient Mobile")
        self.assertIn("7 to 15 digits", issues[0].message)

    def test_a_detail_page_from_another_organization_is_a_404(self):
        other = Organization.objects.create(name="Other", slug="other-detail-clinic")
        other_owner = member(other, "Owner", "other2@example.com")
        theirs = ImportBatch.objects.create(
            organization=other,
            uploaded_by=other_owner,
            purpose=ImportBatch.Purpose.APPOINTMENT,
            original_filename="theirs.csv",
        )

        response = self.client.get(reverse("import_detail", args=[theirs.pk]))

        self.assertEqual(response.status_code, 404)

    def test_a_failed_import_offers_a_replacement_form(self):
        batch = self._failed_import()

        response = self.client.get(reverse("import_detail", args=[batch.pk]))

        self.assertIsNotNone(response.context["replacement_form"])

    def test_a_successful_import_offers_no_replacement_form(self):
        save_campaign_from_csv(
            user=self.owner,
            file=upload("good.csv", f"{HEADER}\n{GOOD_ROW}"),
            title="Good",
            template=self.template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )
        batch = ImportBatch.objects.get(original_filename="good.csv")

        response = self.client.get(reverse("import_detail", args=[batch.pk]))

        self.assertIsNone(response.context["replacement_form"])


class ImportReplacementTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="replace-clinic"
        )
        self.owner = member(self.organization, "Owner", "owner@example.com")
        self.template = MessageTemplate.objects.create(
            organization=self.organization,
            created_by=self.owner,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.owner)
        with self.assertRaises(CsvImportError):
            save_campaign_from_csv(
                user=self.owner,
                file=upload("broken.csv", f"{HEADER}\n{BAD_ROW}"),
                title="Broken",
                template=self.template,
                purpose=Campaign.Purpose.APPOINTMENT,
            )
        self.batch = ImportBatch.objects.get(original_filename="broken.csv")

    def test_a_corrected_file_creates_a_linked_import(self):
        response = self.client.post(
            reverse("import_replace", args=[self.batch.pk]),
            {
                "title": "Corrected",
                "csv_file": upload("fixed.csv", f"{HEADER}\n{GOOD_ROW}"),
            },
        )

        replacement = ImportBatch.objects.get(original_filename="fixed.csv")
        self.assertEqual(replacement.replaces, self.batch)
        self.assertEqual(replacement.status, ImportBatch.Status.IMPORTED)
        campaign = Campaign.objects.get(title="Corrected")
        self.assertRedirects(
            response, reverse("appointment_list_detail", args=[campaign.pk])
        )

    def test_the_original_is_marked_replaced(self):
        self.client.post(
            reverse("import_replace", args=[self.batch.pk]),
            {
                "title": "Corrected",
                "csv_file": upload("fixed.csv", f"{HEADER}\n{GOOD_ROW}"),
            },
        )

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ImportBatch.Status.REPLACED)

    def test_a_replacement_cannot_be_uploaded_twice(self):
        self.client.post(
            reverse("import_replace", args=[self.batch.pk]),
            {
                "title": "Corrected",
                "csv_file": upload("fixed.csv", f"{HEADER}\n{GOOD_ROW}"),
            },
        )

        self.client.post(
            reverse("import_replace", args=[self.batch.pk]),
            {
                "title": "Second try",
                "csv_file": upload("again.csv", f"{HEADER}\n{GOOD_ROW}"),
            },
        )

        self.assertFalse(
            ImportBatch.objects.filter(original_filename="again.csv").exists()
        )

    def test_a_successful_import_cannot_be_replaced(self):
        save_campaign_from_csv(
            user=self.owner,
            file=upload("good.csv", f"{HEADER}\n{GOOD_ROW}"),
            title="Good",
            template=self.template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )
        good = ImportBatch.objects.get(original_filename="good.csv")

        self.client.post(
            reverse("import_replace", args=[good.pk]),
            {
                "title": "Nope",
                "csv_file": upload("nope.csv", f"{HEADER}\n{GOOD_ROW}"),
            },
        )

        self.assertFalse(
            ImportBatch.objects.filter(original_filename="nope.csv").exists()
        )

    def test_a_replacement_that_also_fails_records_its_own_issues(self):
        self.client.post(
            reverse("import_replace", args=[self.batch.pk]),
            {
                "title": "Still broken",
                "csv_file": upload("still.csv", f"{HEADER}\n{BAD_ROW}"),
            },
        )

        replacement = ImportBatch.objects.get(original_filename="still.csv")
        self.assertEqual(replacement.status, ImportBatch.Status.FAILED)
        self.assertTrue(ImportIssue.objects.filter(batch=replacement).exists())

    def test_an_import_from_another_organization_cannot_be_replaced(self):
        other = Organization.objects.create(name="Other", slug="other-replace-clinic")
        other_owner = member(other, "Owner", "other@example.com")
        theirs = ImportBatch.objects.create(
            organization=other,
            uploaded_by=other_owner,
            purpose=ImportBatch.Purpose.APPOINTMENT,
            original_filename="theirs.csv",
            status=ImportBatch.Status.FAILED,
        )

        response = self.client.post(
            reverse("import_replace", args=[theirs.pk]),
            {
                "title": "Cross tenant",
                "csv_file": upload("cross.csv", f"{HEADER}\n{GOOD_ROW}"),
            },
        )

        self.assertEqual(response.status_code, 404)
