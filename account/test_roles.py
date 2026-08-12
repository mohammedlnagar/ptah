"""Role changes and the guards protecting Owner accounts."""

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from account.models import CustomUser, Organization


PASSWORD = "A-secure-test-password-123"


def make_org(slug):
    return Organization.objects.create(name=slug.title(), slug=slug)


def member(organization, role, email, **kwargs):
    user = CustomUser.objects.create_user(
        username=email.split("@")[0],
        email=email,
        organization=organization,
        password=PASSWORD,
        **kwargs,
    )
    user.groups.add(Group.objects.get(name=role))
    return user


class RoleChangeTests(TestCase):
    def setUp(self):
        self.organization = make_org("role-clinic")
        self.owner = member(self.organization, "Owner", "owner@example.com")
        self.admin = member(self.organization, "Admin", "admin@example.com")
        self.operator = member(self.organization, "Operator", "operator@example.com")

    def _set_role(self, member_obj, role):
        return self.client.post(
            reverse("change_member_role", args=[member_obj.pk]), {"role": role}
        )

    def test_owner_can_promote_an_operator_to_admin(self):
        self.client.force_login(self.owner)

        self._set_role(self.operator, "Admin")

        self.assertEqual(
            list(self.operator.groups.values_list("name", flat=True)), ["Admin"]
        )

    def test_changing_a_role_replaces_rather_than_adds(self):
        self.client.force_login(self.owner)

        self._set_role(self.operator, "Approver")

        self.assertEqual(self.operator.groups.count(), 1)

    def test_owner_is_not_an_assignable_role(self):
        self.client.force_login(self.owner)

        self._set_role(self.operator, "Owner")

        self.assertEqual(
            list(self.operator.groups.values_list("name", flat=True)), ["Operator"]
        )

    def test_an_admin_cannot_change_an_owners_role(self):
        self.client.force_login(self.admin)

        response = self._set_role(self.owner, "Operator")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            list(self.owner.groups.values_list("name", flat=True)), ["Owner"]
        )

    def test_an_admin_cannot_suspend_an_owner(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("suspend_member", args=[self.owner.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_an_owner_can_suspend_another_owner(self):
        second_owner = member(self.organization, "Owner", "owner2@example.com")
        self.client.force_login(self.owner)

        self.client.post(reverse("suspend_member", args=[second_owner.pk]))

        second_owner.refresh_from_db()
        self.assertFalse(second_owner.is_active)

    def test_nobody_can_change_their_own_role(self):
        self.client.force_login(self.admin)

        self._set_role(self.admin, "Operator")

        self.assertEqual(
            list(self.admin.groups.values_list("name", flat=True)), ["Admin"]
        )

    def test_a_member_of_another_organization_cannot_be_changed(self):
        outsider = member(make_org("other-clinic"), "Operator", "out@example.com")
        self.client.force_login(self.owner)

        response = self._set_role(outsider, "Admin")

        self.assertEqual(response.status_code, 404)

    def test_an_operator_cannot_change_roles(self):
        self.client.force_login(self.operator)

        response = self._set_role(self.admin, "Operator")

        self.assertEqual(response.status_code, 403)

    def test_an_invalid_role_is_ignored(self):
        self.client.force_login(self.owner)

        self._set_role(self.operator, "Superuser")

        self.assertEqual(
            list(self.operator.groups.values_list("name", flat=True)), ["Operator"]
        )

    def test_the_team_screen_marks_owners_unmanageable_for_admins(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("manage_team"))

        rows = {row["member"].email: row for row in response.context["active_rows"]}
        self.assertFalse(rows["owner@example.com"]["manageable"])
        self.assertTrue(rows["operator@example.com"]["manageable"])
        self.assertTrue(rows["admin@example.com"]["is_self"])
