from django.core.exceptions import ValidationError
from django.test import TestCase

from common.test_utils import make_contact, make_doctor, make_organization
from directory.models import Contact, Department, Doctor
from directory.normalization import canonical_key, normalize_phone_number
from directory.services import resolve_contact, resolve_department, resolve_doctor


class NormalizationTests(TestCase):
    def test_phone_numbers_keep_international_prefix(self):
        self.assertEqual(normalize_phone_number("+971 50 123 4567"), "+971501234567")

    def test_double_zero_prefix_is_treated_as_international(self):
        self.assertEqual(normalize_phone_number("00971501234567"), "+971501234567")

    def test_trailing_float_suffix_from_spreadsheets_is_stripped(self):
        self.assertEqual(normalize_phone_number("0501234567.0"), "0501234567")

    def test_too_short_numbers_are_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("12345")

    def test_blank_numbers_are_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("")

    def test_canonical_key_folds_case_and_whitespace(self):
        self.assertEqual(canonical_key("  Dr.   AHMED  "), "dr. ahmed")


class ContactTests(TestCase):
    def test_saving_populates_the_normalized_mrn(self):
        organization = make_organization()

        contact = make_contact(organization, mrn="  MRN-001 ")

        self.assertEqual(contact.mrn, "MRN-001")
        self.assertEqual(contact.normalized_mrn, "mrn-001")

    def test_blank_mrn_is_stored_as_null(self):
        organization = make_organization()

        contact = make_contact(organization, mrn="")

        self.assertIsNone(contact.mrn)
        self.assertEqual(contact.normalized_mrn, "")

    def test_same_mrn_is_allowed_across_organizations(self):
        first = make_contact(make_organization(), mrn="SHARED")
        second = make_contact(make_organization(), mrn="SHARED")

        self.assertNotEqual(first.organization_id, second.organization_id)
        self.assertEqual(first.normalized_mrn, second.normalized_mrn)


class ResolveServiceTests(TestCase):
    def setUp(self):
        self.organization = make_organization()

    def test_resolve_contact_reuses_an_existing_phone_number(self):
        first = resolve_contact(
            organization=self.organization,
            name="Aisha",
            phone_number="+971501110000",
        )
        second = resolve_contact(
            organization=self.organization,
            name="Aisha Updated",
            phone_number="+971501110000",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.name, "Aisha Updated")
        self.assertEqual(Contact.objects.for_organization(self.organization).count(), 1)

    def test_a_shared_phone_creates_one_contact_per_mrn(self):
        # Families share a mobile; each member keeps their own file number.
        mother = resolve_contact(
            organization=self.organization,
            name="Aisha",
            phone_number="+971501110000",
            mrn="MRN-1",
        )
        child = resolve_contact(
            organization=self.organization,
            name="Omar",
            phone_number="+971501110000",
            mrn="MRN-2",
        )

        self.assertNotEqual(mother.pk, child.pk)
        self.assertEqual(mother.phone_number, child.phone_number)
        self.assertEqual(Contact.objects.for_organization(self.organization).count(), 2)

    def test_resolve_department_is_idempotent_per_organization(self):
        first = resolve_department(organization=self.organization, name="Cardiology")
        second = resolve_department(organization=self.organization, name=" cardiology ")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            Department.objects.for_organization(self.organization).count(), 1
        )

    def test_resolve_doctor_adopts_a_department_for_an_existing_name(self):
        department = resolve_department(organization=self.organization, name="Dermatology")
        without_department = resolve_doctor(organization=self.organization, name="Dr Sara")
        with_department = resolve_doctor(
            organization=self.organization, name="Dr Sara", department=department
        )

        self.assertEqual(without_department.pk, with_department.pk)
        self.assertEqual(with_department.department_id, department.pk)
        self.assertEqual(Doctor.objects.for_organization(self.organization).count(), 1)


class TenantScopingTests(TestCase):
    def test_doctors_are_scoped_to_their_organization(self):
        first = make_organization()
        second = make_organization()
        mine = make_doctor(first)
        theirs = make_doctor(second)

        results = Doctor.objects.for_organization(first)

        self.assertIn(mine, results)
        self.assertNotIn(theirs, results)
