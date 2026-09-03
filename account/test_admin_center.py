"""Admin center: the tabs, and the screens reached from them.

The redesign's nav has five destinations, so invitations, access management,
departments and import history are reached from the tab they belong to rather
than from the nav. Each of those links is gated by the permission that guards
the page it opens, so these tests pin both halves: an Owner sees them, an
Operator does not, and a hidden link is never a link an Operator could have
followed anyway.
"""

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


class AdminCenterTabTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="admin-center-clinic"
        )
        self.owner = member(self.organization, "Owner", "owner@example.com")
        self.client.force_login(self.owner)

    def test_each_tab_renders(self):
        for tab in ("templates", "doctors", "team", "plan"):
            with self.subTest(tab=tab):
                response = self.client.get(reverse("admin_center"), {"tab": tab})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["tab"], tab)

    def test_an_unknown_tab_falls_back_to_templates(self):
        response = self.client.get(reverse("admin_center"), {"tab": "nonsense"})

        self.assertEqual(response.context["tab"], "templates")


class ReachabilityTests(TestCase):
    """Screens outside the twelve routes are still reachable by following links."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="reachability-clinic"
        )
        self.owner = member(self.organization, "Owner", "owner@example.com")
        self.client.force_login(self.owner)

    def test_the_doctors_tab_links_to_departments_and_the_full_list(self):
        response = self.client.get(reverse("admin_center"), {"tab": "doctors"})

        self.assertContains(response, reverse("department_list"))
        self.assertContains(response, reverse("doctor_list"))

    def test_the_team_tab_links_to_invitations_and_access_management(self):
        response = self.client.get(reverse("admin_center"), {"tab": "team"})

        self.assertContains(response, reverse("manage_invites"))
        self.assertContains(response, reverse("manage_team"))

    def test_campaigns_links_to_import_history(self):
        response = self.client.get(reverse("manage_appointments"))

        self.assertContains(response, reverse("import_list"))

    def test_every_linked_screen_actually_opens(self):
        for name in (
            "department_list",
            "doctor_list",
            "manage_invites",
            "manage_team",
            "import_list",
        ):
            with self.subTest(screen=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class LinkPermissionTests(TestCase):
    """An Operator sees neither the links nor the pages behind them."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="link-perms-clinic"
        )
        self.operator = member(self.organization, "Operator", "operator@example.com")
        self.client.force_login(self.operator)

    def test_the_team_tab_hides_administration_links(self):
        response = self.client.get(reverse("admin_center"), {"tab": "team"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("manage_invites"))
        self.assertNotContains(response, reverse("manage_team"))

    def test_the_hidden_pages_are_refused_directly(self):
        # The link being absent is presentation; the page refusing is the control.
        for name in ("manage_invites", "manage_team"):
            with self.subTest(screen=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
