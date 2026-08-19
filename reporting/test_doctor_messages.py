"""The summary text a doctor receives."""

import datetime

from django.test import SimpleTestCase

from campaigns.models import CampaignItem
from reporting.messages import DETAIL_LIMIT, build_doctor_summary


class FakeItem:
    """Stands in for a CampaignItem: the builder only reads these fields."""

    def __init__(self, name, hour, minute=0, status="booked", day=20):
        self.patient_name_snapshot = name
        self.appointment_date = datetime.date(2026, 8, day)
        self.appointment_time = datetime.time(hour, minute)
        self.appointment_status = status

    def get_appointment_status_display(self):
        return dict(CampaignItem.AppointmentStatus.choices).get(
            self.appointment_status, ""
        )


def metrics_for(items):
    return {
        "total": len(items),
        "booked": sum(1 for i in items if i.appointment_status == "booked"),
        "confirmed": sum(1 for i in items if i.appointment_status == "confirmed"),
        "cancelled": sum(1 for i in items if i.appointment_status == "cancelled"),
    }


def build(items, **overrides):
    kwargs = {
        "campaign_title": "August reminders",
        "doctor_name": "Dr Ali",
        "department": "Dental",
        "items": items,
        "metrics": metrics_for(items),
    }
    kwargs.update(overrides)
    return build_doctor_summary(**kwargs)


class ShortListTests(SimpleTestCase):
    def setUp(self):
        self.items = [
            FakeItem("Ahmed Al Mansoori", 9, 30, "confirmed"),
            FakeItem("Sara Khalid", 10, 0, "booked"),
            FakeItem("Fatima Hassan", 11, 15, "cancelled"),
        ]
        self.message = build(self.items)

    def test_it_names_the_doctor_and_the_list(self):
        self.assertIn("Dr Ali", self.message)
        self.assertIn("August reminders", self.message)

    def test_it_names_every_patient(self):
        for name in ("Ahmed Al Mansoori", "Sara Khalid", "Fatima Hassan"):
            self.assertIn(name, self.message)

    def test_it_shows_each_appointment_time(self):
        self.assertIn("09:30", self.message)
        self.assertIn("10:00", self.message)
        self.assertIn("11:15", self.message)

    def test_it_shows_each_status(self):
        self.assertIn("Confirmed", self.message)
        self.assertIn("Booked", self.message)
        self.assertIn("Cancelled", self.message)

    def test_it_shows_the_department_and_the_date(self):
        self.assertIn("Dental", self.message)
        self.assertIn("20 Aug 2026", self.message)

    def test_it_still_carries_the_totals(self):
        self.assertIn("3 total: 1 booked, 1 confirmed, 1 cancelled.", self.message)

    def test_it_does_not_refer_the_doctor_elsewhere(self):
        self.assertNotIn("full list", self.message.lower())

    def test_lines_follow_appointment_order(self):
        body = self.message
        self.assertLess(body.index("Ahmed"), body.index("Sara"))
        self.assertLess(body.index("Sara"), body.index("Fatima"))


class LongListTests(SimpleTestCase):
    def setUp(self):
        # One over the cutoff, so the message must condense.
        self.items = [
            FakeItem(f"Patient {index}", 8 + index // 2, (index % 2) * 30)
            for index in range(DETAIL_LIMIT + 1)
        ]
        self.message = build(self.items)

    def test_no_patient_is_named(self):
        self.assertNotIn("Patient 0", self.message)
        self.assertNotIn("Patient 10", self.message)

    def test_it_gives_the_start_and_end_of_the_day(self):
        self.assertIn("Scheduled 08:00 to 13:00.", self.message)

    def test_it_still_carries_the_totals(self):
        self.assertIn(f"{DETAIL_LIMIT + 1} total:", self.message)

    def test_it_points_at_the_full_list(self):
        self.assertIn("The full list is in Ptah.", self.message)

    def test_exactly_the_limit_is_still_listed_in_full(self):
        items = self.items[:DETAIL_LIMIT]

        message = build(items)

        self.assertIn("Patient 0", message)
        self.assertNotIn("The full list is in Ptah.", message)


class ScrubbedListTests(SimpleTestCase):
    def test_a_scrubbed_list_never_names_anyone(self):
        items = [FakeItem("Ahmed Al Mansoori", 9, 30, "confirmed")]

        message = build(items, name_patients=False)

        self.assertNotIn("Ahmed", message)
        self.assertIn("Scheduled 09:30.", message)
        self.assertIn("1 total:", message)


class EdgeCaseTests(SimpleTestCase):
    def test_a_single_appointment_reads_naturally(self):
        message = build([FakeItem("Ahmed", 9, 30, "booked")])

        self.assertIn("1 appointment ", message)
        self.assertNotIn("1 appointments", message)

    def test_a_span_of_days_is_described_as_a_range(self):
        items = [
            FakeItem("Ahmed", 9, 0, "booked", day=20),
            FakeItem("Sara", 9, 0, "booked", day=22),
        ]

        message = build(items)

        self.assertIn("from 20 Aug to 22 Aug 2026", message)

    def test_a_multi_day_short_list_shows_dates_per_line(self):
        items = [
            FakeItem("Ahmed", 9, 0, "booked", day=20),
            FakeItem("Sara", 9, 0, "booked", day=22),
        ]

        message = build(items)

        self.assertIn("20 Aug 09:00", message)
        self.assertIn("22 Aug 09:00", message)

    def test_items_without_times_do_not_break_the_message(self):
        item = FakeItem("Ahmed", 9, 0, "booked")
        item.appointment_time = None
        item.appointment_date = None

        message = build([item])

        self.assertIn("Ahmed", message)
        self.assertIn("1 total:", message)

    def test_a_missing_department_is_omitted_cleanly(self):
        message = build([FakeItem("Ahmed", 9, 0)], department="")

        self.assertNotIn(" · ", message.splitlines()[1])
        self.assertIn("1 appointment", message)
