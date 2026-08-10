from django.contrib.auth.models import Group
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.test import TestCase

from .forms import CustomUserCreationForm
from .models import CustomUser, Organization, OrganizationSubscription


class OrganizationSignupTests(TestCase):
    def test_signup_creates_tenant_subscription_and_owner(self):
        form = CustomUserCreationForm(
            data={
                "organization_name": "Example Clinic",
                "username": "owner",
                "email": "owner@example.com",
                "mobile_number": "+971501234567",
                "password1": "A-secure-test-password-123",
                "password2": "A-secure-test-password-123",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.organization.name, "Example Clinic")
        self.assertTrue(user.groups.filter(name="Owner").exists())
        owner = Group.objects.get(name="Owner")
        self.assertTrue(owner.permissions.filter(codename="add_campaign").exists())
        self.assertFalse(owner.permissions.filter(codename="add_organization").exists())
        self.assertTrue(
            OrganizationSubscription.objects.filter(organization=user.organization).exists()
        )

    def test_employee_can_reference_only_one_organization(self):
        first = Organization.objects.create(name="First", slug="first")
        second = Organization.objects.create(name="Second", slug="second")
        user = CustomUser.objects.create_user(
            username="employee", email="employee@example.com", organization=first
        )
        user.organization = second
        user.save(update_fields=("organization",))
        self.assertEqual(CustomUser.objects.get(pk=user.pk).organization, second)


class PasswordHashingTests(TestCase):
    def test_new_passwords_use_argon2id(self):
        encoded = make_password("A-secure-test-password-123")

        self.assertEqual(identify_hasher(encoded).algorithm, "argon2")
        self.assertTrue(check_password("A-secure-test-password-123", encoded))
