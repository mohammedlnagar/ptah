from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from appointments.models import Appointment
from common.models import validate_related_organizations
from common.test_utils import make_contact, make_organization, make_user
from directory.models import Contact


class TenantQuerySetTests(TestCase):
    def setUp(self):
        self.first = make_organization()
        self.second = make_organization()
        self.first_contact = make_contact(self.first)
        self.second_contact = make_contact(self.second)

    def test_for_organization_excludes_other_tenants(self):
        results = Contact.objects.for_organization(self.first)

        self.assertIn(self.first_contact, results)
        self.assertNotIn(self.second_contact, results)

    def test_for_user_scopes_to_the_users_organization(self):
        employee = make_user(self.first)

        results = Contact.objects.for_user(employee)

        self.assertEqual(list(results), [self.first_contact])

    def test_for_user_returns_everything_for_platform_superusers(self):
        platform_admin = make_user(None, is_superuser=True, is_staff=True)

        results = Contact.objects.for_user(platform_admin)

        self.assertIn(self.first_contact, results)
        self.assertIn(self.second_contact, results)

    def test_for_user_returns_nothing_for_unassigned_non_superuser(self):
        # The employee_requires_organization constraint makes this state
        # unreachable in the database, so the guard is exercised in memory to
        # prove the queryset fails closed rather than leaking every tenant.
        stranger = get_user_model()(username="stranger", email="stranger@example.com")

        self.assertFalse(Contact.objects.for_user(stranger).exists())


class ValidateRelatedOrganizationsTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.other = make_organization()

    def test_rejects_relation_owned_by_another_organization(self):
        appointment = Appointment(
            organization=self.organization,
            contact=make_contact(self.other),
            scheduled_at=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            validate_related_organizations(appointment, "contact")

    def test_allows_relation_in_the_same_organization(self):
        appointment = Appointment(
            organization=self.organization,
            contact=make_contact(self.organization),
            scheduled_at=timezone.now(),
        )

        validate_related_organizations(appointment, "contact")

    def test_ignores_unset_relations(self):
        appointment = Appointment(
            organization=self.organization,
            contact=make_contact(self.organization),
            scheduled_at=timezone.now(),
        )

        validate_related_organizations(appointment, "doctor", "source_import")


class CustomUserValidationTests(TestCase):
    """The organization requirement is enforced by the database constraint.

    ``full_clean()`` runs ``validate_constraints()``, so callers already get a
    ValidationError rather than an IntegrityError. No model-level ``clean()``
    duplicates this: the signup form assigns the organization in ``save()``,
    after validation runs, so a ``clean()`` check would reject every new tenant.
    """

    def test_employee_without_an_organization_is_rejected(self):
        user = get_user_model()(
            username="employee",
            email="employee@example.com",
            password="hashed-placeholder",
        )

        with self.assertRaises(ValidationError) as context:
            user.full_clean()

        self.assertIn("employee_requires_organization", str(context.exception))

    def test_superuser_may_be_unassigned(self):
        platform_admin = get_user_model()(
            username="platform",
            email="platform@example.com",
            password="hashed-placeholder",
            is_superuser=True,
        )

        platform_admin.full_clean()

    def test_employee_with_an_organization_validates(self):
        employee = get_user_model()(
            username="employee",
            email="employee@example.com",
            password="hashed-placeholder",
            organization=make_organization(),
        )

        employee.full_clean()
