"""Subscription limit checks.

The plan fields have existed since the tenant refactor but nothing read them,
so an organization on the free plan could add unlimited users and campaigns.
These helpers make the stored limits mean something. They deliberately do not
touch billing: nothing here changes a subscription, it only reports whether
one more seat or campaign is allowed.

An organization with no subscription row is treated as unlimited rather than
blocked, so a missing record can never lock a tenant out of its own workspace.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone


def _plan_for(organization):
    subscription = getattr(organization, "subscription", None)
    return subscription.plan if subscription else None


def seats_in_use(organization):
    """Active members plus invitations that could still be accepted.

    Outstanding invites count so an admin cannot issue more links than the
    plan has seats and discover the problem only when people try to join.
    """
    from .models import CustomUser, OrganizationInvite

    active_members = CustomUser.objects.filter(
        organization=organization, is_active=True
    ).count()
    outstanding = sum(
        1
        for invite in OrganizationInvite.objects.filter(
            organization=organization, used_at__isnull=True
        )
        if invite.is_usable
    )
    return active_members + outstanding


def seat_limit(organization):
    plan = _plan_for(organization)
    return plan.max_users if plan else None


def check_seat_available(organization):
    """Raise if the organization cannot take on one more member."""
    limit = seat_limit(organization)
    if limit is None:
        return
    if seats_in_use(organization) >= limit:
        raise ValidationError(
            f"Your plan allows {limit} member(s). "
            "Remove or suspend someone, or upgrade, before adding another."
        )


def campaigns_this_month(organization, on=None):
    from campaigns.models import Campaign

    today = on or timezone.localdate()
    return Campaign.objects.for_organization(organization).filter(
        created_at__year=today.year, created_at__month=today.month
    ).count()


def campaign_limit(organization):
    plan = _plan_for(organization)
    return plan.max_monthly_campaigns if plan else None


def check_campaign_available(organization):
    """Raise if the organization has used up this month's campaign allowance."""
    limit = campaign_limit(organization)
    if limit is None:
        return
    if campaigns_this_month(organization) >= limit:
        raise ValidationError(
            f"Your plan allows {limit} campaign(s) per month. "
            "The allowance resets at the start of next month."
        )


def usage_summary(organization):
    """Numbers for display; None limits render as unlimited."""
    return {
        "seats_used": seats_in_use(organization),
        "seat_limit": seat_limit(organization),
        "campaigns_used": campaigns_this_month(organization),
        "campaign_limit": campaign_limit(organization),
    }
