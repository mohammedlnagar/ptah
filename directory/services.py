from django.core.exceptions import ValidationError
from django.db import transaction

from .normalization import canonical_key, clean_display_text
from .models import Contact, Department, Doctor


@transaction.atomic
def resolve_contact(*, organization, name, phone_number, mrn=""):
    contact = Contact.objects.select_for_update().filter(
        organization=organization,
        phone_number=phone_number,
    ).first()
    if contact is None:
        contact = Contact(
            organization=organization,
            name=name,
            phone_number=phone_number,
            mrn=mrn or None,
        )
    else:
        contact.name = name
        if mrn and contact.mrn and canonical_key(mrn) != contact.normalized_mrn:
            raise ValidationError(
                "The phone number is already linked to a different MRN."
            )
        if mrn and not contact.mrn:
            contact.mrn = mrn
    contact.full_clean()
    contact.save()
    return contact


@transaction.atomic
def resolve_department(*, organization, name):
    display_name = clean_display_text(name)
    normalized_name = canonical_key(display_name)
    department = Department.objects.select_for_update().filter(
        organization=organization,
        normalized_name=normalized_name,
    ).first()
    if department is None:
        department = Department(
            organization=organization,
            name=display_name,
            normalized_name=normalized_name,
        )
        department.full_clean()
        department.save()
    return department


@transaction.atomic
def resolve_doctor(*, organization, name, department=None):
    display_name = clean_display_text(name)
    normalized_name = canonical_key(display_name)
    doctor = Doctor.objects.select_for_update().filter(
        organization=organization,
        normalized_name=normalized_name,
        department=department,
    ).first()
    if doctor is None and department is not None:
        doctor = Doctor.objects.select_for_update().filter(
            organization=organization,
            normalized_name=normalized_name,
            department__isnull=True,
        ).first()
        if doctor:
            doctor.department = department
    if doctor is None:
        doctor = Doctor(
            organization=organization,
            department=department,
            name=display_name,
            normalized_name=normalized_name,
        )
    doctor.full_clean()
    doctor.save()
    return doctor
