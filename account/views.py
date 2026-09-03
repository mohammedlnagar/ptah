from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from common.access import tenant_or_403

from .forms import (
    CustomUserCreationForm,
    CustomUserUpdateForm,
    InvitedUserCreationForm,
    LoginForm,
    OrganizationInviteForm,
    OrganizationSettingsForm,
)
from .models import CustomUser, OrganizationInvite
from .services import check_seat_available, usage_summary


def register(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = CustomUserCreationForm()
    return render(request, "account/register.html", {"form": form})


def register_with_invite(request, token):
    invite = get_object_or_404(
        OrganizationInvite.objects.select_related("organization"), token=token
    )
    if not invite.is_usable:
        return render(
            request,
            "account/invite_unavailable.html",
            {"invite": invite},
            status=410,
        )
    if request.method == "POST":
        form = InvitedUserCreationForm(request.POST, invite=invite)
        if form.is_valid():
            form.save()
            # No login here: the account is inactive until an admin approves it.
            return render(
                request,
                "account/invite_accepted.html",
                {"invite": invite},
            )
    else:
        form = InvitedUserCreationForm(invite=invite)
    return render(
        request,
        "account/register_invite.html",
        {"form": form, "invite": invite},
    )


@require_GET
def validate_registration(request):
    field = request.GET.get("field")
    value = request.GET.get("value", "").strip()
    if field not in {"username", "email"} or not value:
        return JsonResponse({"valid": False, "message": "Invalid request."}, status=400)
    exists = CustomUser.objects.filter(**{field: value}).exists()
    return JsonResponse(
        {
            "valid": not exists,
            "message": f"This {field} is already registered." if exists else "",
        }
    )


def user_login(request):
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect("home")
    else:
        form = LoginForm()
    return render(request, "account/login.html", {"form": form})


@require_POST
def user_logout(request):
    logout(request)
    return redirect("login")


@login_required
def profile(request):
    """Profile card with the operator's own real totals.

    Both counts are attributed through sent_by, so they describe work this
    person did rather than what happened in their workspace.
    """
    from messaging.models import CampaignMessage

    sent = CampaignMessage.objects.filter(
        sent_by=request.user, status=CampaignMessage.Status.SENT
    )
    return render(
        request,
        "account/profile.html",
        {
            "profile_user": request.user,
            "messages_sent": sent.count(),
            "campaigns_worked": sent.values("campaign_item__campaign").distinct().count(),
        },
    )


@login_required
def edit_profile(request):
    if request.method == "POST":
        user_form = CustomUserUpdateForm(request.POST, instance=request.user)
        if user_form.is_valid():
            user_form.save()
            messages.success(request, "Profile updated")
            return redirect("profile")
    else:
        user_form = CustomUserUpdateForm(instance=request.user)
    return render(
        request,
        "account/edit_profile.html",
        {"user_form": user_form},
    )


@login_required
@permission_required("account.change_organization", raise_exception=True)
def organization_settings(request):
    organization = tenant_or_403(request)
    if request.method == "POST":
        form = OrganizationSettingsForm(request.POST, instance=organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Workspace settings saved.")
            return redirect("organization_settings")
    else:
        form = OrganizationSettingsForm(instance=organization)
    return render(
        request,
        "account/organization_settings.html",
        {"form": form, "organization": organization},
    )


@login_required
@permission_required("account.add_organizationinvite", raise_exception=True)
def manage_invites(request):
    organization = tenant_or_403(request)
    if request.method == "POST":
        form = OrganizationInviteForm(request.POST)
        if form.is_valid():
            try:
                check_seat_available(organization)
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
                return redirect("manage_invites")
            invite = form.save(commit=False)
            invite.organization = organization
            invite.created_by = request.user
            invite.full_clean()
            invite.save()
            messages.success(
                request, "Invitation link created. Share it with your colleague."
            )
            return redirect("manage_invites")
    else:
        form = OrganizationInviteForm()
    invites = (
        OrganizationInvite.objects.filter(organization=organization)
        .select_related("created_by", "used_by")
    )
    return render(
        request,
        "account/invites.html",
        {
            "form": form,
            "invites": invites,
            "usage": usage_summary(organization),
        },
    )


@login_required
@permission_required("account.change_organizationinvite", raise_exception=True)
@require_POST
def revoke_invite(request, invite_id):
    organization = tenant_or_403(request)
    invite = get_object_or_404(
        OrganizationInvite, pk=invite_id, organization=organization
    )
    if invite.is_usable:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=("revoked_at", "updated_at"))
        messages.success(request, "Invitation revoked.")
    else:
        messages.error(request, "That invitation is no longer active.")
    return redirect("manage_invites")


ASSIGNABLE_ROLES = OrganizationInvite.Role


def _is_owner(user):
    return user.groups.filter(name="Owner").exists()


def _editable_member(request, organization, user_id, **filters):
    """Fetch a colleague the requester is allowed to act on.

    Owner accounts are only modifiable by another Owner, so an Admin cannot
    suspend or demote the person who owns the workspace.
    """
    member = get_object_or_404(
        CustomUser, pk=user_id, organization=organization, **filters
    )
    if _is_owner(member) and not _is_owner(request.user):
        raise PermissionDenied("Only an Owner can manage another Owner.")
    return member


@login_required
@permission_required("account.change_customuser", raise_exception=True)
def manage_team(request):
    organization = tenant_or_403(request)
    members = (
        CustomUser.objects.filter(organization=organization)
        .prefetch_related("groups")
        .order_by("-is_active", "email")
    )
    requester_is_owner = _is_owner(request.user)
    rows = []
    for member in members:
        member_is_owner = any(
            group.name == "Owner" for group in member.groups.all()
        )
        rows.append(
            {
                "member": member,
                "roles": [group.name for group in member.groups.all()],
                # An Admin may not touch an Owner, and nobody edits themselves.
                "manageable": (
                    member.pk != request.user.pk
                    and (requester_is_owner or not member_is_owner)
                ),
                "is_self": member.pk == request.user.pk,
            }
        )
    return render(
        request,
        "account/team.html",
        {
            "pending_rows": [row for row in rows if not row["member"].is_active],
            "active_rows": [row for row in rows if row["member"].is_active],
            "assignable_roles": ASSIGNABLE_ROLES.choices,
        },
    )


@login_required
@permission_required("account.change_customuser", raise_exception=True)
@require_POST
def change_member_role(request, user_id):
    organization = tenant_or_403(request)
    member = _editable_member(request, organization, user_id)
    if member.pk == request.user.pk:
        messages.error(request, "You cannot change your own role.")
        return redirect("manage_team")
    role = request.POST.get("role")
    if role not in ASSIGNABLE_ROLES.values:
        messages.error(request, "Select a valid role.")
        return redirect("manage_team")
    # Replace rather than add: a member holds exactly one role.
    member.groups.set([Group.objects.get(name=role)])
    messages.success(request, f"{member.email} is now {role}.")
    return redirect("manage_team")


@login_required
@permission_required("account.change_customuser", raise_exception=True)
@require_POST
def approve_member(request, user_id):
    organization = tenant_or_403(request)
    member = _editable_member(request, organization, user_id, is_active=False)
    try:
        # The pending account does not hold a seat yet; approving claims one.
        check_seat_available(organization)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("manage_team")
    member.is_active = True
    member.save(update_fields=("is_active",))
    messages.success(request, f"{member.email} can now sign in.")
    return redirect("manage_team")


@login_required
@permission_required("account.change_customuser", raise_exception=True)
@require_POST
def suspend_member(request, user_id):
    organization = tenant_or_403(request)
    if str(user_id) == str(request.user.pk):
        messages.error(request, "You cannot suspend your own account.")
        return redirect("manage_team")
    member = _editable_member(request, organization, user_id, is_active=True)
    member.is_active = False
    member.save(update_fields=("is_active",))
    messages.success(request, f"{member.email} can no longer sign in.")
    return redirect("manage_team")


@login_required
def admin_center(request):
    """One workspace administration screen with four tabs.

    Template approval, doctors, team and plan each already had their own page.
    The redesign folds them into tabs, so this gathers all four datasets and
    the templates render whichever tab is selected. Each section is omitted
    when the viewer lacks the permission that guards its dedicated page, so
    the tabs never expose more than the old screens did.
    """
    from directory.models import Doctor
    from messaging.models import MessageTemplateRevision

    organization = tenant_or_403(request)
    tab = request.GET.get("tab", "templates")
    if tab not in {"templates", "doctors", "team", "plan"}:
        tab = "templates"

    can_approve = request.user.has_perm("messaging.change_messagetemplate")
    can_view_templates = request.user.has_perm("messaging.view_messagetemplate")
    can_view_doctors = request.user.has_perm("directory.view_doctor")
    can_view_team = request.user.has_perm("account.change_customuser")
    can_view_plan = request.user.has_perm("account.change_organization")

    awaiting = []
    if can_view_templates:
        awaiting = list(
            MessageTemplateRevision.objects.for_organization(organization)
            .filter(
                is_current=True,
                approval_status=MessageTemplateRevision.ApprovalStatus.PENDING,
            )
            .select_related("template", "created_by")
            .order_by("template__name")
        )

    doctors = []
    if can_view_doctors:
        doctors = list(
            Doctor.objects.for_organization(organization)
            .select_related("department")
            .order_by("name")
        )

    team_rows = []
    if can_view_team:
        members = (
            CustomUser.objects.filter(organization=organization)
            .prefetch_related("groups")
            .order_by("-is_active", "email")
        )
        for member in members:
            team_rows.append(
                {
                    "member": member,
                    "roles": [group.name for group in member.groups.all()],
                }
            )

    subscription = getattr(organization, "subscription", None)
    usage = usage_summary(organization) if can_view_plan else None

    return render(
        request,
        "account/admin_center.html",
        {
            "tab": tab,
            "awaiting": awaiting,
            "awaiting_count": len(awaiting),
            "doctors": doctors,
            "team_rows": team_rows,
            "subscription": subscription,
            "usage": usage,
            "can_approve": can_approve,
            "can_view_templates": can_view_templates,
            "can_view_doctors": can_view_doctors,
            "can_view_team": can_view_team,
            "can_view_plan": can_view_plan,
        },
    )
