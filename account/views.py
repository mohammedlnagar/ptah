from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, permission_required
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
)
from .models import CustomUser, OrganizationInvite


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
    return render(request, "account/profile.html", {"profile_user": request.user})


@login_required
def edit_profile(request):
    if request.method == "POST":
        user_form = CustomUserUpdateForm(request.POST, instance=request.user)
        if user_form.is_valid():
            user_form.save()
            return redirect("profile")
    else:
        user_form = CustomUserUpdateForm(instance=request.user)
    return render(
        request,
        "account/edit_profile.html",
        {"user_form": user_form},
    )


@login_required
@permission_required("account.add_organizationinvite", raise_exception=True)
def manage_invites(request):
    organization = tenant_or_403(request)
    if request.method == "POST":
        form = OrganizationInviteForm(request.POST)
        if form.is_valid():
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
        {"form": form, "invites": invites},
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


@login_required
@permission_required("account.change_customuser", raise_exception=True)
def manage_team(request):
    organization = tenant_or_403(request)
    members = (
        CustomUser.objects.filter(organization=organization)
        .prefetch_related("groups")
        .order_by("-is_active", "email")
    )
    return render(
        request,
        "account/team.html",
        {
            "pending_members": [user for user in members if not user.is_active],
            "active_members": [user for user in members if user.is_active],
        },
    )


@login_required
@permission_required("account.change_customuser", raise_exception=True)
@require_POST
def approve_member(request, user_id):
    organization = tenant_or_403(request)
    member = get_object_or_404(
        CustomUser, pk=user_id, organization=organization, is_active=False
    )
    member.is_active = True
    member.save(update_fields=("is_active",))
    messages.success(request, f"{member.email} can now sign in.")
    return redirect("manage_team")


@login_required
@permission_required("account.change_customuser", raise_exception=True)
@require_POST
def suspend_member(request, user_id):
    organization = tenant_or_403(request)
    member = get_object_or_404(
        CustomUser, pk=user_id, organization=organization, is_active=True
    )
    if member.pk == request.user.pk:
        messages.error(request, "You cannot suspend your own account.")
        return redirect("manage_team")
    member.is_active = False
    member.save(update_fields=("is_active",))
    messages.success(request, f"{member.email} can no longer sign in.")
    return redirect("manage_team")
