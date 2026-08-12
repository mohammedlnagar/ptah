"""Subscription seat and campaign limits."""

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from account.models import (
    CustomUser,
    Organization,
    OrganizationInvite,
    OrganizationSubscription,
    SubscriptionPlan,
)
from account.services import (
    campaigns_this_month,
    check_campaign_available,
    check_seat_available,
    seats_in_use,
)
from campaigns.models import Campaign


PASSWORD = "A-secure-test-password-123"


def make_plan(max_users=5, max_monthly_campaigns=20, code="test-plan"):
    return SubscriptionPlan.objects.create(
        name=code.title(),
        code=code,
        max_users=max_users,
        max_monthly_campaigns=max_monthly_campaigns,
    )


def subscribe(organization, plan):
    from django.utils import timezone

    return OrganizationSubscription.objects.create(
        organization=organization,
        plan=plan,
        status=OrganizationSubscription.Status.ACTIVE,
        starts_on=timezone.localdate(),
    )


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


class SeatCountingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Clinic", slug="seat-clinic")
        self.owner = member(self.organization, "Owner", "owner@example.com")

    def test_active_members_occupy_seats(self):
        member(self.organization, "Operator", "op@example.com")

        self.assertEqual(seats_in_use(self.organization), 2)

    def test_suspended_members_do_not_occupy_seats(self):
        member(self.organization, "Operator", "op@example.com", is_active=False)

        self.assertEqual(seats_in_use(self.organization), 1)

    def test_outstanding_invitations_reserve_a_seat(self):
        OrganizationInvite.objects.create(
            organization=self.organization, created_by=self.owner
        )

        self.assertEqual(seats_in_use(self.organization), 2)

    def test_a_used_invitation_does_not_double_count(self):
        joiner = member(
            self.organization, "Operator", "joiner@example.com", is_active=False
        )
        from django.utils import timezone

        OrganizationInvite.objects.create(
            organization=self.organization,
            created_by=self.owner,
            used_by=joiner,
            used_at=timezone.now(),
        )

        # The invite is spent and the joiner is not active yet.
        self.assertEqual(seats_in_use(self.organization), 1)

    def test_an_expired_invitation_frees_its_seat(self):
        import datetime

        from django.utils import timezone

        OrganizationInvite.objects.create(
            organization=self.organization,
            created_by=self.owner,
            expires_at=timezone.now() - datetime.timedelta(days=1),
        )

        self.assertEqual(seats_in_use(self.organization), 1)

    def test_no_subscription_means_no_limit(self):
        for index in range(10):
            member(self.organization, "Operator", f"op{index}@example.com")

        check_seat_available(self.organization)

    def test_reaching_the_limit_raises(self):
        subscribe(self.organization, make_plan(max_users=2))
        member(self.organization, "Operator", "op@example.com")

        with self.assertRaises(ValidationError):
            check_seat_available(self.organization)

    def test_below_the_limit_is_allowed(self):
        subscribe(self.organization, make_plan(max_users=3))
        member(self.organization, "Operator", "op@example.com")

        check_seat_available(self.organization)


class SeatEnforcementViewTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Clinic", slug="seat-views")
        self.owner = member(self.organization, "Owner", "owner@example.com")
        subscribe(self.organization, make_plan(max_users=2, code="two-seats"))
        self.client.force_login(self.owner)

    def test_an_invitation_is_refused_when_the_plan_is_full(self):
        member(self.organization, "Operator", "op@example.com")

        response = self.client.post(
            reverse("manage_invites"), {"role": OrganizationInvite.Role.OPERATOR}
        )

        self.assertRedirects(response, reverse("manage_invites"))
        self.assertEqual(OrganizationInvite.objects.count(), 0)

    def test_an_invitation_is_allowed_with_a_spare_seat(self):
        response = self.client.post(
            reverse("manage_invites"), {"role": OrganizationInvite.Role.OPERATOR}
        )

        self.assertRedirects(response, reverse("manage_invites"))
        self.assertEqual(OrganizationInvite.objects.count(), 1)

    def test_a_second_invitation_is_refused_because_the_first_reserves_a_seat(self):
        self.client.post(
            reverse("manage_invites"), {"role": OrganizationInvite.Role.OPERATOR}
        )

        self.client.post(
            reverse("manage_invites"), {"role": OrganizationInvite.Role.OPERATOR}
        )

        self.assertEqual(OrganizationInvite.objects.count(), 1)

    def test_approval_is_refused_when_the_plan_is_full(self):
        member(self.organization, "Operator", "op@example.com")
        pending = member(
            self.organization, "Operator", "pending@example.com", is_active=False
        )

        self.client.post(reverse("approve_member", args=[pending.pk]))

        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

    def test_suspending_frees_a_seat_for_approval(self):
        occupier = member(self.organization, "Operator", "op@example.com")
        pending = member(
            self.organization, "Operator", "pending@example.com", is_active=False
        )
        self.client.post(reverse("suspend_member", args=[occupier.pk]))

        self.client.post(reverse("approve_member", args=[pending.pk]))

        pending.refresh_from_db()
        self.assertTrue(pending.is_active)


class CampaignLimitTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Clinic", slug="campaign-limits"
        )
        self.owner = member(self.organization, "Owner", "owner@example.com")

    def _campaign(self):
        return Campaign.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Campaign",
            purpose=Campaign.Purpose.MARKETING,
        )

    def test_counts_only_this_organizations_campaigns(self):
        other = Organization.objects.create(name="Other", slug="other-campaign-limits")
        other_owner = member(other, "Owner", "other@example.com")
        Campaign.objects.create(
            organization=other,
            created_by=other_owner,
            title="Theirs",
            purpose=Campaign.Purpose.MARKETING,
        )
        self._campaign()

        self.assertEqual(campaigns_this_month(self.organization), 1)

    def test_no_subscription_means_no_limit(self):
        self._campaign()

        check_campaign_available(self.organization)

    def test_reaching_the_monthly_limit_raises(self):
        subscribe(
            self.organization, make_plan(max_monthly_campaigns=1, code="one-campaign")
        )
        self._campaign()

        with self.assertRaises(ValidationError):
            check_campaign_available(self.organization)

    def test_below_the_monthly_limit_is_allowed(self):
        subscribe(
            self.organization, make_plan(max_monthly_campaigns=2, code="two-campaigns")
        )
        self._campaign()

        check_campaign_available(self.organization)
