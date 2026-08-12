"""Factory helpers shared by the domain-app test suites.

Kept in ``common`` because it is the one package every tenant app already
depends on for ``TenantModel``. Values default to unique-per-call so tests can
create several records without tripping the per-organization unique
constraints.
"""

from itertools import count

from django.contrib.auth import get_user_model
from django.utils import timezone

from account.models import Organization


_sequence = count(1)


def next_suffix():
    return next(_sequence)


def make_organization(name=None, **kwargs):
    suffix = next_suffix()
    name = name or f"Clinic {suffix}"
    kwargs.setdefault("slug", f"clinic-{suffix}")
    return Organization.objects.create(name=name, **kwargs)


def make_user(organization=None, **kwargs):
    suffix = next_suffix()
    kwargs.setdefault("username", f"user{suffix}")
    kwargs.setdefault("email", f"user{suffix}@example.com")
    return get_user_model().objects.create_user(
        organization=organization, **kwargs
    )


def make_contact(organization, **kwargs):
    from directory.models import Contact

    suffix = next_suffix()
    kwargs.setdefault("name", f"Patient {suffix}")
    kwargs.setdefault("phone_number", f"+9715{suffix:08d}")
    return Contact.objects.create(organization=organization, **kwargs)


def make_department(organization, **kwargs):
    from directory.models import Department

    kwargs.setdefault("name", f"Department {next_suffix()}")
    return Department.objects.create(organization=organization, **kwargs)


def make_doctor(organization, **kwargs):
    from directory.models import Doctor

    kwargs.setdefault("name", f"Doctor {next_suffix()}")
    return Doctor.objects.create(organization=organization, **kwargs)


def make_import_batch(organization, uploaded_by=None, **kwargs):
    from imports.models import ImportBatch

    uploaded_by = uploaded_by or make_user(organization)
    kwargs.setdefault("purpose", ImportBatch.Purpose.APPOINTMENT)
    kwargs.setdefault("original_filename", "upload.csv")
    return ImportBatch.objects.create(
        organization=organization, uploaded_by=uploaded_by, **kwargs
    )


def make_appointment(organization, contact=None, **kwargs):
    from appointments.models import Appointment

    contact = contact or make_contact(organization)
    kwargs.setdefault("scheduled_at", timezone.now())
    return Appointment.objects.create(
        organization=organization, contact=contact, **kwargs
    )


def make_template(organization, created_by=None, **kwargs):
    from messaging.models import MessageTemplate

    created_by = created_by or make_user(organization)
    kwargs.setdefault("name", f"Template {next_suffix()}")
    kwargs.setdefault("content", "Hello #patient_name")
    return MessageTemplate.objects.create(
        organization=organization, created_by=created_by, **kwargs
    )


def make_revision(template, created_by=None, **kwargs):
    from messaging.models import MessageTemplateRevision

    created_by = created_by or template.created_by
    kwargs.setdefault("version", 1)
    kwargs.setdefault("content", template.content)
    return MessageTemplateRevision.objects.create(
        organization=template.organization,
        template=template,
        created_by=created_by,
        **kwargs,
    )


def make_campaign(organization, created_by=None, **kwargs):
    from campaigns.models import Campaign

    created_by = created_by or make_user(organization)
    kwargs.setdefault("title", f"Campaign {next_suffix()}")
    kwargs.setdefault("purpose", Campaign.Purpose.MARKETING)
    return Campaign.objects.create(
        organization=organization, created_by=created_by, **kwargs
    )


def make_campaign_item(campaign, contact=None, **kwargs):
    from campaigns.models import CampaignItem

    organization = campaign.organization
    contact = contact or make_contact(organization)
    kwargs.setdefault("row_number", next_suffix())
    kwargs.setdefault("patient_name_snapshot", contact.name)
    kwargs.setdefault("phone_number_snapshot", contact.phone_number)
    return CampaignItem.objects.create(
        organization=organization, campaign=campaign, contact=contact, **kwargs
    )


def make_campaign_message(campaign_item, **kwargs):
    from messaging.models import CampaignMessage

    kwargs.setdefault("rendered_content", "Hello there")
    return CampaignMessage.objects.create(
        organization=campaign_item.organization,
        campaign_item=campaign_item,
        **kwargs,
    )
