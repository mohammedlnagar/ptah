from django.db import transaction

from .normalization import canonical_key, clean_display_text
from .models import Contact, Department, Doctor


@transaction.atomic
def resolve_contact(*, organization, name, phone_number, mrn=""):
    """Find or create the patient a CSV row refers to.

    The MRN is the identity: a patient keeps their record even if their phone
    number changed. Phone is only an identity for patients who have no MRN at
    all, which is what lets a family share one mobile — each member resolves to
    their own record instead of colliding on the number.
    """
    normalized_mrn = canonical_key(mrn)
    contact = None
    if normalized_mrn:
        contact = Contact.objects.select_for_update().filter(
            organization=organization,
            normalized_mrn=normalized_mrn,
        ).first()
        if contact is None:
            # Seen before on this number but without an MRN: adopt the MRN onto
            # that record rather than leaving a duplicate patient behind.
            contact = Contact.objects.select_for_update().filter(
                organization=organization,
                phone_number=phone_number,
                normalized_mrn="",
            ).first()
    else:
        contact = Contact.objects.select_for_update().filter(
            organization=organization,
            phone_number=phone_number,
            normalized_mrn="",
        ).first()

    if contact is None:
        contact = Contact(organization=organization)
    contact.name = name
    contact.phone_number = phone_number
    if mrn:
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
