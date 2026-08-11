from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import CustomUserCreationForm, CustomUserUpdateForm, LoginForm
from .models import CustomUser


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
