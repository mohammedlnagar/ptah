from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from common.access import tenant_or_403

from .forms import DepartmentForm, DoctorForm
from .models import Department, Doctor


@login_required
@permission_required("directory.view_doctor", raise_exception=True)
def doctor_list(request):
    organization = tenant_or_403(request)
    query = (request.GET.get("q") or "").strip()
    doctors = Doctor.objects.for_organization(organization).select_related(
        "department"
    )
    if query:
        doctors = doctors.filter(
            Q(name__icontains=query)
            | Q(code__icontains=query)
            | Q(department__name__icontains=query)
        )
    return render(
        request,
        "directory/doctor_list.html",
        {"doctors": doctors, "query": query},
    )


@login_required
@permission_required("directory.add_doctor", raise_exception=True)
def doctor_create(request):
    organization = tenant_or_403(request)
    if request.method == "POST":
        form = DoctorForm(request.POST, organization=organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Doctor added.")
            return redirect("doctor_list")
    else:
        form = DoctorForm(organization=organization)
    return render(
        request,
        "directory/doctor_form.html",
        {"form": form, "heading": "Add a doctor"},
    )


@login_required
@permission_required("directory.change_doctor", raise_exception=True)
def doctor_edit(request, doctor_id):
    organization = tenant_or_403(request)
    doctor = get_object_or_404(
        Doctor.objects.for_organization(organization), pk=doctor_id
    )
    if request.method == "POST":
        form = DoctorForm(request.POST, instance=doctor, organization=organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Doctor updated.")
            return redirect("doctor_list")
    else:
        form = DoctorForm(instance=doctor, organization=organization)
    return render(
        request,
        "directory/doctor_form.html",
        {"form": form, "heading": f"Edit {doctor.name}", "doctor": doctor},
    )


@login_required
@permission_required("directory.view_department", raise_exception=True)
def department_list(request):
    organization = tenant_or_403(request)
    departments = Department.objects.for_organization(organization).annotate(
        doctor_count=Count("doctors")
    )
    return render(
        request,
        "directory/department_list.html",
        {"departments": departments},
    )


@login_required
@permission_required("directory.add_department", raise_exception=True)
def department_create(request):
    organization = tenant_or_403(request)
    if request.method == "POST":
        form = DepartmentForm(request.POST, organization=organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Department added.")
            return redirect("department_list")
    else:
        form = DepartmentForm(organization=organization)
    return render(
        request,
        "directory/department_form.html",
        {"form": form, "heading": "Add a department"},
    )


@login_required
@permission_required("directory.change_department", raise_exception=True)
def department_edit(request, department_id):
    organization = tenant_or_403(request)
    department = get_object_or_404(
        Department.objects.for_organization(organization), pk=department_id
    )
    if request.method == "POST":
        form = DepartmentForm(
            request.POST, instance=department, organization=organization
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Department updated.")
            return redirect("department_list")
    else:
        form = DepartmentForm(instance=department, organization=organization)
    return render(
        request,
        "directory/department_form.html",
        {"form": form, "heading": f"Edit {department.name}"},
    )
