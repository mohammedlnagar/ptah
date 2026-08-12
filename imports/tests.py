from django.core.exceptions import ValidationError
from django.test import TestCase

from common.test_utils import make_import_batch, make_organization, make_user
from imports.models import ImportBatch, ImportIssue


class ImportBatchTests(TestCase):
    def setUp(self):
        self.organization = make_organization()

    def test_defaults_to_uploaded(self):
        batch = make_import_batch(self.organization)

        self.assertEqual(batch.status, ImportBatch.Status.UPLOADED)
        self.assertEqual(batch.row_count, 0)
        self.assertEqual(batch.errors, [])

    def test_only_a_failed_batch_can_be_replaced(self):
        succeeded = make_import_batch(
            self.organization, status=ImportBatch.Status.IMPORTED
        )
        replacement = ImportBatch(
            organization=self.organization,
            uploaded_by=make_user(self.organization),
            purpose=ImportBatch.Purpose.APPOINTMENT,
            original_filename="retry.csv",
            replaces=succeeded,
        )

        with self.assertRaises(ValidationError):
            replacement.full_clean()

    def test_replacing_a_failed_batch_is_allowed(self):
        failed = make_import_batch(self.organization, status=ImportBatch.Status.FAILED)
        replacement = ImportBatch(
            organization=self.organization,
            uploaded_by=make_user(self.organization),
            purpose=ImportBatch.Purpose.APPOINTMENT,
            original_filename="retry.csv",
            replaces=failed,
        )

        replacement.full_clean()

    def test_rejects_an_uploader_from_another_organization(self):
        outsider = make_user(make_organization())
        batch = ImportBatch(
            organization=self.organization,
            uploaded_by=outsider,
            purpose=ImportBatch.Purpose.APPOINTMENT,
            original_filename="upload.csv",
        )

        with self.assertRaises(ValidationError):
            batch.full_clean()

    def test_scoped_to_the_owning_organization(self):
        mine = make_import_batch(self.organization)
        theirs = make_import_batch(make_organization())

        results = ImportBatch.objects.for_organization(self.organization)

        self.assertIn(mine, results)
        self.assertNotIn(theirs, results)


class ImportIssueTests(TestCase):
    def test_issues_are_linked_to_their_batch(self):
        organization = make_organization()
        batch = make_import_batch(organization, status=ImportBatch.Status.FAILED)

        ImportIssue.objects.create(
            organization=organization,
            batch=batch,
            row_number=4,
            column="Patient Mobile",
            message="Enter a phone number containing 7 to 15 digits.",
        )

        self.assertEqual(batch.issues.count(), 1)
