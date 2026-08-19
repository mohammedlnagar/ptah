"""Patient identity: MRN is the key, phone is shared."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from common.test_utils import make_organization
from directory.models import Contact
from directory.services import resolve_contact


SHARED_PHONE = "+971501110000"


class SharedPhoneNumberTests(TestCase):
    def setUp(self):
        self.organization = make_organization()

    def _resolve(self, name, mrn="", phone=SHARED_PHONE):
        return resolve_contact(
            organization=self.organization, name=name, phone_number=phone, mrn=mrn
        )

    def test_one_phone_carries_several_patients(self):
        first = self._resolve("Aisha", mrn="MRN-1")
        second = self._resolve("Omar", mrn="MRN-2")
        third = self._resolve("Layla", mrn="MRN-3")

        self.assertEqual(len({first.pk, second.pk, third.pk}), 3)
        self.assertEqual(
            Contact.objects.for_organization(self.organization).count(), 3
        )

    def test_the_same_mrn_resolves_to_the_same_patient(self):
        first = self._resolve("Aisha", mrn="MRN-1")
        again = self._resolve("Aisha Renamed", mrn="MRN-1")

        self.assertEqual(first.pk, again.pk)
        self.assertEqual(again.name, "Aisha Renamed")

    def test_an_mrn_matches_even_when_the_phone_changed(self):
        first = self._resolve("Aisha", mrn="MRN-1")

        moved = self._resolve("Aisha", mrn="MRN-1", phone="+971509998888")

        self.assertEqual(first.pk, moved.pk)
        self.assertEqual(moved.phone_number, "+971509998888")

    def test_mrn_matching_ignores_case_and_padding(self):
        first = self._resolve("Aisha", mrn="MRN-1")

        again = self._resolve("Aisha", mrn="  mrn-1 ")

        self.assertEqual(first.pk, again.pk)

    def test_rows_without_an_mrn_reuse_the_anonymous_contact(self):
        first = self._resolve("Aisha")
        again = self._resolve("Aisha Updated")

        self.assertEqual(first.pk, again.pk)
        self.assertEqual(
            Contact.objects.for_organization(self.organization).count(), 1
        )

    def test_an_mrn_is_adopted_onto_a_contact_that_had_none(self):
        # The first import had no MR number; a later one supplies it. That is
        # the same patient, not a new one.
        anonymous = self._resolve("Aisha")

        identified = self._resolve("Aisha", mrn="MRN-1")

        self.assertEqual(anonymous.pk, identified.pk)
        self.assertEqual(identified.mrn, "MRN-1")
        self.assertEqual(
            Contact.objects.for_organization(self.organization).count(), 1
        )

    def test_an_mrn_less_row_does_not_hijack_an_identified_patient(self):
        identified = self._resolve("Aisha", mrn="MRN-1")

        anonymous = self._resolve("Unknown caller")

        self.assertNotEqual(identified.pk, anonymous.pk)
        self.assertEqual(anonymous.mrn, None)

    def test_mrn_stays_unique_within_an_organization(self):
        self._resolve("Aisha", mrn="MRN-1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(
                organization=self.organization,
                name="Impostor",
                phone_number="+971502223333",
                mrn="MRN-1",
            )

    def test_only_one_anonymous_contact_per_phone(self):
        self._resolve("Aisha")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(
                organization=self.organization,
                name="Duplicate",
                phone_number=SHARED_PHONE,
            )

    def test_a_shared_phone_does_not_leak_across_organizations(self):
        mine = self._resolve("Aisha", mrn="MRN-1")
        other = resolve_contact(
            organization=make_organization(),
            name="Someone else",
            phone_number=SHARED_PHONE,
            mrn="MRN-1",
        )

        self.assertNotEqual(mine.pk, other.pk)
        self.assertNotEqual(mine.organization_id, other.organization_id)
