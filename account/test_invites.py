"""Invite-based onboarding: link creation, registration, and approval."""

import datetime

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import CustomUser, Organization, OrganizationInvite


PASSWORD = "A-secure-test-password-123"


def make_org(name, slug):
    return Organization.objects.create(name=name, slug=slug)


def make_member(organization, email, role=None, **kwargs):
    user = CustomUser.objects.create_user(
        username=email.split("@")[0],
        email=email,
        organization=organization,
        password=PASSWORD,
        **kwargs,
    )
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


class InviteModelTests(TestCase):
    def setUp(self):
        self.organization = make_org("Clinic", "clinic-invite-model")
        self.owner = make_member(self.organization, "owner@example.com", "Owner")

    def _invite(self, **kwargs):
        return OrganizationInvite.objects.create(
            organization=self.organization, created_by=self.owner, **kwargs
        )

    def test_tokens_are_unique_and_unguessable_length(self):
        first = self._invite()
        second = self._invite()

        self.assertNotEqual(first.token, second.token)
        self.assertGreaterEqual(len(first.token), 32)

    def test_a_fresh_invite_is_usable(self):
        invite = self._invite()

        self.assertTrue(invite.is_usable)
        self.assertEqual(invite.state, "active")

    def test_an_expired_invite_is_not_usable(self):
        invite = self._invite(expires_at=timezone.now() - datetime.timedelta(days=1))

        self.assertFalse(invite.is_usable)
        self.assertEqual(invite.state, "expired")

    def test_a_revoked_invite_is_not_usable(self):
        invite = self._invite(revoked_at=timezone.now())

        self.assertFalse(invite.is_usable)
        self.assertEqual(invite.state, "revoked")

    def test_a_used_invite_is_not_usable(self):
        invite = self._invite(used_at=timezone.now())

        self.assertFalse(invite.is_usable)
        self.assertEqual(invite.state, "used")

    def test_owner_is_not_an_invitable_role(self):
        # Prevents an Admin from using an invite to escalate past their role.
        self.assertNotIn("Owner", OrganizationInvite.Role.values)


class InviteCreationViewTests(TestCase):
    def setUp(self):
        self.organization = make_org("Clinic", "clinic-invite-view")
        self.owner = make_member(self.organization, "owner@example.com", "Owner")
        self.operator = make_member(self.organization, "operator@example.com", "Operator")

    def test_owner_can_create_an_invitation(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("manage_invites"), {"role": OrganizationInvite.Role.OPERATOR}
        )

        self.assertRedirects(response, reverse("manage_invites"))
        invite = OrganizationInvite.objects.get()
        self.assertEqual(invite.organization, self.organization)
        self.assertEqual(invite.created_by, self.owner)

    def test_admin_can_create_an_invitation(self):
        admin = make_member(self.organization, "admin@example.com", "Admin")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("manage_invites"), {"role": OrganizationInvite.Role.OPERATOR}
        )

        self.assertRedirects(response, reverse("manage_invites"))
        self.assertEqual(OrganizationInvite.objects.count(), 1)

    def test_operator_cannot_reach_the_invite_screen(self):
        self.client.force_login(self.operator)

        response = self.client.get(reverse("manage_invites"))

        self.assertEqual(response.status_code, 403)

    def test_invites_from_other_organizations_are_not_listed(self):
        other = make_org("Other", "other-clinic")
        other_owner = make_member(other, "other-owner@example.com", "Owner")
        OrganizationInvite.objects.create(
            organization=other, created_by=other_owner
        )
        mine = OrganizationInvite.objects.create(
            organization=self.organization, created_by=self.owner
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("manage_invites"))

        listed = list(response.context["invites"])
        self.assertEqual(listed, [mine])

    def test_revoking_an_invite_disables_it(self):
        invite = OrganizationInvite.objects.create(
            organization=self.organization, created_by=self.owner
        )
        self.client.force_login(self.owner)

        self.client.post(reverse("revoke_invite", args=[invite.pk]))

        invite.refresh_from_db()
        self.assertFalse(invite.is_usable)

    def test_an_invite_from_another_organization_cannot_be_revoked(self):
        other = make_org("Other", "other-clinic-revoke")
        other_owner = make_member(other, "other-owner@example.com", "Owner")
        invite = OrganizationInvite.objects.create(
            organization=other, created_by=other_owner
        )
        self.client.force_login(self.owner)

        response = self.client.post(reverse("revoke_invite", args=[invite.pk]))

        self.assertEqual(response.status_code, 404)
        invite.refresh_from_db()
        self.assertTrue(invite.is_usable)


class InvitedRegistrationTests(TestCase):
    def setUp(self):
        self.organization = make_org("Clinic", "clinic-register")
        self.owner = make_member(self.organization, "owner@example.com", "Owner")
        self.invite = OrganizationInvite.objects.create(
            organization=self.organization,
            created_by=self.owner,
            role=OrganizationInvite.Role.OPERATOR,
        )

    def _register(self, token, email="joiner@example.com"):
        return self.client.post(
            reverse("register_with_invite", args=[token]),
            {
                "username": email.split("@")[0],
                "email": email,
                "mobile_number": "+971501234567",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

    def test_registering_joins_the_inviting_organization(self):
        response = self._register(self.invite.token)

        self.assertEqual(response.status_code, 200)
        user = CustomUser.objects.get(email="joiner@example.com")
        self.assertEqual(user.organization, self.organization)

    def test_the_new_account_starts_inactive(self):
        self._register(self.invite.token)

        user = CustomUser.objects.get(email="joiner@example.com")
        self.assertFalse(user.is_active)

    def test_the_role_comes_from_the_invite(self):
        self._register(self.invite.token)

        user = CustomUser.objects.get(email="joiner@example.com")
        self.assertTrue(user.groups.filter(name="Operator").exists())

    def test_no_new_organization_is_created(self):
        # The migrations seed a legacy organization, so compare against the
        # count before registering rather than assuming an empty table.
        before = Organization.objects.count()

        self._register(self.invite.token)

        self.assertEqual(Organization.objects.count(), before)

    def test_the_invite_is_consumed(self):
        self._register(self.invite.token)

        self.invite.refresh_from_db()
        self.assertFalse(self.invite.is_usable)
        self.assertEqual(self.invite.used_by.email, "joiner@example.com")

    def test_the_same_link_cannot_be_used_twice(self):
        self._register(self.invite.token, email="first@example.com")

        response = self._register(self.invite.token, email="second@example.com")

        self.assertEqual(response.status_code, 410)
        self.assertFalse(CustomUser.objects.filter(email="second@example.com").exists())

    def test_an_expired_link_is_refused(self):
        self.invite.expires_at = timezone.now() - datetime.timedelta(days=1)
        self.invite.save(update_fields=("expires_at",))

        response = self._register(self.invite.token)

        self.assertEqual(response.status_code, 410)
        self.assertFalse(CustomUser.objects.filter(email="joiner@example.com").exists())

    def test_a_revoked_link_is_refused(self):
        self.invite.revoked_at = timezone.now()
        self.invite.save(update_fields=("revoked_at",))

        response = self._register(self.invite.token)

        self.assertEqual(response.status_code, 410)

    def test_an_unknown_token_is_a_404(self):
        response = self.client.get(
            reverse("register_with_invite", args=["not-a-real-token"])
        )

        self.assertEqual(response.status_code, 404)

    def test_an_invited_user_cannot_sign_in_before_approval(self):
        self._register(self.invite.token)

        signed_in = self.client.login(username="joiner@example.com", password=PASSWORD)

        self.assertFalse(signed_in)


class TeamApprovalTests(TestCase):
    def setUp(self):
        self.organization = make_org("Clinic", "clinic-approval")
        self.owner = make_member(self.organization, "owner@example.com", "Owner")
        self.pending = make_member(
            self.organization, "pending@example.com", "Operator", is_active=False
        )

    def test_pending_members_are_listed(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("manage_team"))

        self.assertIn(self.pending, response.context["pending_members"])
        self.assertIn(self.owner, response.context["active_members"])

    def test_approving_lets_the_member_sign_in(self):
        self.client.force_login(self.owner)

        self.client.post(reverse("approve_member", args=[self.pending.pk]))

        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_active)
        self.client.logout()
        self.assertTrue(
            self.client.login(username="pending@example.com", password=PASSWORD)
        )

    def test_operators_cannot_approve(self):
        operator = make_member(self.organization, "operator@example.com", "Operator")
        self.client.force_login(operator)

        response = self.client.post(
            reverse("approve_member", args=[self.pending.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_active)

    def test_a_member_of_another_organization_cannot_be_approved(self):
        other = make_org("Other", "other-clinic-approval")
        outsider = make_member(
            other, "outsider@example.com", "Operator", is_active=False
        )
        self.client.force_login(self.owner)

        response = self.client.post(reverse("approve_member", args=[outsider.pk]))

        self.assertEqual(response.status_code, 404)
        outsider.refresh_from_db()
        self.assertFalse(outsider.is_active)

    def test_members_of_other_organizations_are_not_listed(self):
        other = make_org("Other", "other-clinic-listing")
        outsider = make_member(other, "outsider@example.com", "Operator")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("manage_team"))

        self.assertNotIn(outsider, response.context["active_members"])

    def test_suspending_blocks_sign_in(self):
        member = make_member(self.organization, "member@example.com", "Operator")
        self.client.force_login(self.owner)

        self.client.post(reverse("suspend_member", args=[member.pk]))

        member.refresh_from_db()
        self.assertFalse(member.is_active)

    def test_an_owner_cannot_suspend_themselves(self):
        self.client.force_login(self.owner)

        self.client.post(reverse("suspend_member", args=[self.owner.pk]))

        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
