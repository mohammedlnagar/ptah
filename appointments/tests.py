from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from appointments.models import Appointment, AppointmentStatusEvent
from common.test_utils import (
    make_appointment,
    make_contact,
    make_import_batch,
    make_organization,
    make_user,
)
from imports.models import ImportBatch


class AppointmentTests(TestCase):
    def setUp(self):
        self.organization = make_organization()

    def test_defaults_to_booked(self):
        appointment = make_appointment(self.organization)

        self.assertEqual(appointment.status, Appointment.Status.BOOKED)

    def test_rejects_a_contact_from_another_organization(self):
        foreign_contact = make_contact(make_organization())
        appointment = Appointment(
            organization=self.organization,
            contact=foreign_contact,
            scheduled_at=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_rejects_a_marketing_import_as_the_source(self):
        marketing_batch = make_import_batch(
            self.organization, purpose=ImportBatch.Purpose.MARKETING
        )
        appointment = Appointment(
            organization=self.organization,
            contact=make_contact(self.organization),
            source_import=marketing_batch,
            scheduled_at=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_scoped_to_the_owning_organization(self):
        mine = make_appointment(self.organization)
        theirs = make_appointment(make_organization())

        results = Appointment.objects.for_organization(self.organization)

        self.assertIn(mine, results)
        self.assertNotIn(theirs, results)


class AppointmentStatusEventTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.user = make_user(self.organization)
        self.appointment = make_appointment(self.organization)

    def test_records_a_transition(self):
        event = AppointmentStatusEvent.objects.create(
            organization=self.organization,
            appointment=self.appointment,
            previous_status=Appointment.Status.BOOKED,
            new_status=Appointment.Status.CONFIRMED,
            changed_by=self.user,
        )

        self.assertEqual(self.appointment.status_events.count(), 1)
        self.assertEqual(event.new_status, Appointment.Status.CONFIRMED)

    def test_blank_previous_status_is_allowed_for_the_first_event(self):
        event = AppointmentStatusEvent(
            organization=self.organization,
            appointment=self.appointment,
            previous_status="",
            new_status=Appointment.Status.BOOKED,
            changed_by=self.user,
        )

        event.full_clean()

    def test_rejects_a_no_op_transition(self):
        event = AppointmentStatusEvent(
            organization=self.organization,
            appointment=self.appointment,
            previous_status=Appointment.Status.BOOKED,
            new_status=Appointment.Status.BOOKED,
            changed_by=self.user,
        )

        with self.assertRaises(ValidationError):
            event.full_clean()
