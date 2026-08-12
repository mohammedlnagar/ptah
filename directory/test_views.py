"""Tenant-scoped doctor and department management screens."""

from django.test import TestCase
from django.urls import reverse

from common.test_utils import (
    make_department,
    make_doctor,
    make_organization,
    make_user,
)
from directory.models import Department, Doctor


def member(organization, role, email):
    from django.contrib.auth.models import Group

    user = make_user(organization, email=email, password="test-password-123")
    user.groups.add(Group.objects.get(name=role))
    return user


class DoctorViewTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.admin = member(self.organization, "Admin", "admin@example.com")
        self.operator = member(self.organization, "Operator", "operator@example.com")

    def test_list_shows_only_this_organizations_doctors(self):
        mine = make_doctor(self.organization, name="Dr Mine")
        theirs = make_doctor(make_organization(), name="Dr Theirs")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("doctor_list"))

        self.assertIn(mine, response.context["doctors"])
        self.assertNotIn(theirs, response.context["doctors"])

    def test_search_filters_by_name(self):
        make_doctor(self.organization, name="Dr Cardio")
        make_doctor(self.organization, name="Dr Derma")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("doctor_list"), {"q": "Cardio"})

        names = [doctor.name for doctor in response.context["doctors"]]
        self.assertEqual(names, ["Dr Cardio"])

    def test_admin_can_create_a_doctor(self):
        department = make_department(self.organization)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("doctor_create"),
            {
                "name": "Dr New",
                "department": department.pk,
                "code": "D-1",
                "phone_number": "+971501112222",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("doctor_list"))
        doctor = Doctor.objects.get(name="Dr New")
        self.assertEqual(doctor.organization, self.organization)
        self.assertEqual(doctor.department, department)

    def test_created_doctor_is_normalized(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse("doctor_create"),
            {"name": "  Dr   Spaced  ", "code": "", "phone_number": "", "is_active": "on"},
        )

        doctor = Doctor.objects.get(normalized_name="dr spaced")
        self.assertEqual(doctor.name, "Dr Spaced")

    def test_operator_cannot_create_a_doctor(self):
        self.client.force_login(self.operator)

        response = self.client.post(
            reverse("doctor_create"), {"name": "Dr Nope", "is_active": "on"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Doctor.objects.filter(name="Dr Nope").exists())

    def test_operator_can_still_view_the_list(self):
        self.client.force_login(self.operator)

        response = self.client.get(reverse("doctor_list"))

        self.assertEqual(response.status_code, 200)

    def test_a_doctor_from_another_organization_cannot_be_edited(self):
        outsider = make_doctor(make_organization(), name="Dr Outsider")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("doctor_edit", args=[outsider.pk]))

        self.assertEqual(response.status_code, 404)

    def test_department_choices_are_limited_to_the_organization(self):
        mine = make_department(self.organization)
        theirs = make_department(make_organization())
        self.client.force_login(self.admin)

        response = self.client.get(reverse("doctor_create"))

        choices = response.context["form"].fields["department"].queryset
        self.assertIn(mine, choices)
        self.assertNotIn(theirs, choices)

    def test_a_duplicate_doctor_code_is_reported_as_a_field_error(self):
        make_doctor(self.organization, name="Dr First", code="D-1")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("doctor_create"),
            {"name": "Dr Second", "code": "d-1", "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("code", response.context["form"].errors)
        self.assertFalse(Doctor.objects.filter(name="Dr Second").exists())

    def test_a_blank_doctor_code_can_repeat(self):
        make_doctor(self.organization, name="Dr First", code="")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("doctor_create"),
            {"name": "Dr Second", "code": "", "is_active": "on"},
        )

        self.assertRedirects(response, reverse("doctor_list"))

    def test_a_department_from_another_organization_is_rejected(self):
        foreign = make_department(make_organization())
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("doctor_create"),
            {"name": "Dr Cross", "department": foreign.pk, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Doctor.objects.filter(name="Dr Cross").exists())


class DepartmentViewTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.admin = member(self.organization, "Admin", "admin@example.com")

    def test_list_is_scoped_and_counts_doctors(self):
        department = make_department(self.organization, name="Cardiology")
        make_doctor(self.organization, department=department)
        make_department(make_organization(), name="Foreign")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("department_list"))

        listed = list(response.context["departments"])
        self.assertEqual([d.name for d in listed], ["Cardiology"])
        self.assertEqual(listed[0].doctor_count, 1)

    def test_admin_can_create_a_department(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("department_create"),
            {"name": "Dermatology", "code": "DERM", "is_active": "on"},
        )

        self.assertRedirects(response, reverse("department_list"))
        department = Department.objects.get(name="Dermatology")
        self.assertEqual(department.organization, self.organization)
        self.assertEqual(department.normalized_name, "dermatology")

    def test_duplicate_names_in_one_organization_are_rejected(self):
        make_department(self.organization, name="Cardiology")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("department_create"), {"name": "cardiology", "is_active": "on"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Department.objects.for_organization(self.organization)
            .filter(normalized_name="cardiology")
            .count(),
            1,
        )

    def test_the_same_name_is_allowed_in_another_organization(self):
        make_department(make_organization(), name="Cardiology")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("department_create"), {"name": "Cardiology", "is_active": "on"}
        )

        self.assertRedirects(response, reverse("department_list"))
