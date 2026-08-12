import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from campaigns.models import Campaign, CampaignItem
from common.test_utils import (
    make_campaign,
    make_campaign_item,
    make_contact,
    make_organization,
)


class CampaignTests(TestCase):
    def test_defaults_to_draft(self):
        campaign = make_campaign(make_organization())

        self.assertEqual(campaign.status, Campaign.Status.DRAFT)
        self.assertEqual(campaign.summary, {})

    def test_scoped_to_the_owning_organization(self):
        organization = make_organization()
        mine = make_campaign(organization)
        theirs = make_campaign(make_organization())

        results = Campaign.objects.for_organization(organization)

        self.assertIn(mine, results)
        self.assertNotIn(theirs, results)


class CampaignItemTests(TestCase):
    def setUp(self):
        self.organization = make_organization()

    def test_marketing_items_do_not_require_appointment_details(self):
        campaign = make_campaign(self.organization, purpose=Campaign.Purpose.MARKETING)
        item = make_campaign_item(campaign)

        item.full_clean()

    def test_appointment_items_require_date_time_and_status(self):
        campaign = make_campaign(
            self.organization, purpose=Campaign.Purpose.APPOINTMENT
        )
        contact = make_contact(self.organization)
        item = CampaignItem(
            organization=self.organization,
            campaign=campaign,
            contact=contact,
            row_number=1,
            patient_name_snapshot=contact.name,
            phone_number_snapshot=contact.phone_number,
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_appointment_items_validate_when_details_are_present(self):
        campaign = make_campaign(
            self.organization, purpose=Campaign.Purpose.APPOINTMENT
        )
        contact = make_contact(self.organization)
        item = CampaignItem(
            organization=self.organization,
            campaign=campaign,
            contact=contact,
            row_number=1,
            patient_name_snapshot=contact.name,
            phone_number_snapshot=contact.phone_number,
            appointment_date=datetime.date(2026, 8, 20),
            appointment_time=datetime.time(10, 30),
            appointment_status=CampaignItem.AppointmentStatus.BOOKED,
        )

        item.full_clean()

    def test_rejects_a_contact_from_another_organization(self):
        campaign = make_campaign(self.organization)
        foreign_contact = make_contact(make_organization())
        item = CampaignItem(
            organization=self.organization,
            campaign=campaign,
            contact=foreign_contact,
            row_number=1,
            patient_name_snapshot="Someone",
            phone_number_snapshot="+971500000000",
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_row_numbers_are_unique_within_a_campaign(self):
        campaign = make_campaign(self.organization)
        make_campaign_item(campaign, row_number=1)

        with self.assertRaises(Exception):
            make_campaign_item(campaign, row_number=1)
