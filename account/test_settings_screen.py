"""Workspace settings, including the retention default."""

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from account.models import CustomUser, Organization


PASSWORD = "A-secure-test-password-123"


def member(organization, role, email):
    user = CustomUser.objects.create_user(
        username=email.split("@")[0],
        email=email,
        organization=organization,
        password=PASSWORD,
    )
    user.groups.add(Group.objects.get(name=role))
    return user


class OrganizationSettingsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="settings-clinic"
        )
        self.owner = member(self.organization, "Owner", "owner@example.com")

    def _post(self, **overrides):
        payload = {
            "name": self.organization.name,
            "timezone": "Asia/Dubai",
            "whatsapp_url_template": "https://wa.me/{phone}?text={message}",
            "campaign_retention_days": "2",
        }
        payload.update(overrides)
        return self.client.post(reverse("organization_settings"), payload)

    def test_the_default_retention_is_two_days(self):
        self.assertEqual(self.organization.campaign_retention_days, 2)

    def test_an_owner_can_change_the_retention_window(self):
        self.client.force_login(self.owner)

        response = self._post(campaign_retention_days="14")

        self.assertRedirects(response, reverse("organization_settings"))
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.campaign_retention_days, 14)

    def test_zero_is_accepted_and_means_never(self):
        self.client.force_login(self.owner)

        self._post(campaign_retention_days="0")

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.campaign_retention_days, 0)

    def test_a_negative_window_is_rejected(self):
        self.client.force_login(self.owner)

        response = self._post(campaign_retention_days="-1")

        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.campaign_retention_days, 2)

    def test_a_whatsapp_template_missing_placeholders_is_rejected(self):
        self.client.force_login(self.owner)

        response = self._post(whatsapp_url_template="https://wa.me/")

        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertIn("{phone}", self.organization.whatsapp_url_template)

    def test_an_invalid_timezone_is_rejected(self):
        self.client.force_login(self.owner)

        response = self._post(timezone="Mars/Olympus")

        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.timezone, "Asia/Dubai")

    def test_an_operator_cannot_reach_the_screen(self):
        self.client.force_login(member(self.organization, "Operator", "op@example.com"))

        response = self.client.get(reverse("organization_settings"))

        self.assertEqual(response.status_code, 403)

    def test_an_admin_cannot_change_workspace_settings(self):
        # change_organization is intentionally Owner-only.
        self.client.force_login(member(self.organization, "Admin", "admin@example.com"))

        response = self.client.get(reverse("organization_settings"))

        self.assertEqual(response.status_code, 403)

    def test_the_screen_only_ever_edits_your_own_workspace(self):
        Organization.objects.create(name="Other", slug="other-settings-clinic")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("organization_settings"))

        self.assertEqual(response.context["organization"], self.organization)
