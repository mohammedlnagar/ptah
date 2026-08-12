import datetime

from django.test import TestCase

from campaigns.models import Campaign, CampaignItem, DoctorSummary
from common.test_utils import (
    make_campaign,
    make_campaign_item,
    make_campaign_message,
    make_doctor,
    make_organization,
)
from messaging.models import CampaignMessage
from reporting.services import refresh_campaign_summary


class RefreshCampaignSummaryTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.campaign = make_campaign(
            self.organization, purpose=Campaign.Purpose.APPOINTMENT
        )
        self.doctor = make_doctor(self.organization)

    def _add_item(self, status, doctor=None):
        return make_campaign_item(
            self.campaign,
            doctor=doctor,
            appointment_date=datetime.date(2026, 8, 20),
            appointment_time=datetime.time(9, 0),
            appointment_status=status,
        )

    def test_counts_items_and_appointment_statuses(self):
        self._add_item(CampaignItem.AppointmentStatus.BOOKED)
        self._add_item(CampaignItem.AppointmentStatus.CONFIRMED)
        self._add_item(CampaignItem.AppointmentStatus.CANCELLED)

        summary = refresh_campaign_summary(self.campaign)

        self.assertEqual(summary["total_items"], 3)
        self.assertEqual(summary["appointments"]["booked"], 1)
        self.assertEqual(summary["appointments"]["confirmed"], 1)
        self.assertEqual(summary["appointments"]["cancelled"], 1)

    def test_counts_message_statuses(self):
        item = self._add_item(CampaignItem.AppointmentStatus.BOOKED)
        make_campaign_message(item, status=CampaignMessage.Status.SENT)

        summary = refresh_campaign_summary(self.campaign)

        self.assertEqual(summary["messages"]["operator_marked_sent"], 1)
        self.assertEqual(summary["messages"]["pending"], 0)

    def test_builds_per_doctor_metrics_and_summary_records(self):
        self._add_item(CampaignItem.AppointmentStatus.BOOKED, doctor=self.doctor)
        self._add_item(CampaignItem.AppointmentStatus.CONFIRMED, doctor=self.doctor)

        summary = refresh_campaign_summary(self.campaign)

        metrics = summary["doctors"][str(self.doctor.pk)]
        self.assertEqual(metrics["total"], 2)
        self.assertEqual(metrics["booked"], 1)
        self.assertEqual(metrics["confirmed"], 1)
        self.assertEqual(
            DoctorSummary.objects.filter(campaign=self.campaign).count(), 1
        )

    def test_summary_is_persisted_on_the_campaign(self):
        self._add_item(CampaignItem.AppointmentStatus.BOOKED)

        refresh_campaign_summary(self.campaign)
        self.campaign.refresh_from_db()

        self.assertEqual(self.campaign.summary["total_items"], 1)

    def test_stale_doctor_summaries_are_removed(self):
        item = self._add_item(
            CampaignItem.AppointmentStatus.BOOKED, doctor=self.doctor
        )
        refresh_campaign_summary(self.campaign)
        self.assertEqual(DoctorSummary.objects.filter(campaign=self.campaign).count(), 1)

        item.doctor = None
        item.save(update_fields=("doctor",))
        refresh_campaign_summary(self.campaign)

        self.assertEqual(DoctorSummary.objects.filter(campaign=self.campaign).count(), 0)
