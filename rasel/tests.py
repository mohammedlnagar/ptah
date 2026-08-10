import datetime

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from account.models import CustomUser, Organization
from rasel.models import (
    Campaign,
    CampaignItem,
    CampaignMessage,
    Contact,
    Department,
    Doctor,
    MessageTemplate,
)
from rasel.forms import CampaignUploadForm, MessageTemplateForm
from rasel.utilities.csv_handler import save_campaign_from_csv


class TenantSchemaTests(TestCase):
    def setUp(self):
        self.first = Organization.objects.create(name="First Clinic", slug="first-clinic")
        self.second = Organization.objects.create(name="Second Clinic", slug="second-clinic")
        self.user = CustomUser.objects.create_user(
            username="operator",
            email="operator@example.com",
            organization=self.first,
            password="test-password",
        )

    def test_phone_uniqueness_is_scoped_to_organization(self):
        Contact.objects.create(
            organization=self.first, name="Patient A", phone_number="+971500000001"
        )
        Contact.objects.create(
            organization=self.second, name="Patient B", phone_number="+971500000001"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(
                organization=self.first, name="Duplicate", phone_number="+971500000001"
            )

    def test_cross_tenant_department_is_rejected(self):
        department = Department.objects.create(organization=self.second, name="Dental")
        doctor = Doctor(organization=self.first, department=department, name="Dr Example")
        with self.assertRaises(ValidationError):
            doctor.full_clean()

    def test_whatsapp_link_uses_snapshot_content(self):
        contact = Contact.objects.create(
            organization=self.first, name="Patient", phone_number="+971500000002"
        )
        template = MessageTemplate.objects.create(
            organization=self.first,
            created_by=self.user,
            name="Reminder",
            content="Hello #patient_name",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        campaign = Campaign.objects.create(
            organization=self.first,
            created_by=self.user,
            title="Tomorrow",
            template=template,
        )
        item = CampaignItem.objects.create(
            organization=self.first,
            campaign=campaign,
            contact=contact,
            row_number=1,
            patient_name_snapshot="Patient",
            phone_number_snapshot=contact.phone_number,
            appointment_date=datetime.date(2026, 8, 11),
            appointment_time=datetime.time(9, 0),
            appointment_status=CampaignItem.AppointmentStatus.BOOKED,
        )
        message = CampaignMessage.objects.create(
            organization=self.first,
            campaign_item=item,
            template=template,
            rendered_content="Hello Patient",
        )
        self.assertIn("971500000002", message.whatsapp_url())
        self.assertIn("Hello%20Patient", message.whatsapp_url())

    def test_appointment_csv_creates_snapshots_and_summary(self):
        template = MessageTemplate.objects.create(
            organization=self.first,
            created_by=self.user,
            name="Reminder",
            content="Hello #patient_name, your appointment with #doctor is #appointment_status.",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        csv_file = SimpleUploadedFile(
            "appointments.csv",
            (
                "Patient Name,Patient Mobile,MR No.,Appointment Date,Appointment Date/Time,"
                "Consultant,Doctor Department,Appointment Status,Remarks\n"
                "Mona,+971500000003,MR-1,11-08-2026,11-08-2026 09:30,Dr Ali,Dental,Confirmed,Arrive early\n"
            ).encode(),
            content_type="text/csv",
        )
        campaign = save_campaign_from_csv(
            user=self.user,
            file=csv_file,
            title="August reminders",
            template=template,
            purpose=Campaign.Purpose.APPOINTMENT,
        )
        item = campaign.items.get()
        self.assertEqual(item.mrn_snapshot, "MR-1")
        self.assertEqual(item.appointment_status, CampaignItem.AppointmentStatus.CONFIRMED)
        self.assertEqual(item.doctor_name_snapshot, "Dr Ali")
        self.assertEqual(campaign.summary["total_items"], 1)
        self.assertIn("Confirmed", item.message.rendered_content)

    def test_tenant_forms_validate_without_preassigned_hidden_fields(self):
        template_form = MessageTemplateForm(
            data={"name": "Marketing", "purpose": "marketing", "content": "Hello"},
            user=self.user,
        )
        self.assertTrue(template_form.is_valid(), template_form.errors)

        template = MessageTemplate.objects.create(
            organization=self.first,
            created_by=self.user,
            name="Approved reminder",
            content="Hello",
            approval_status=MessageTemplate.ApprovalStatus.APPROVED,
        )
        campaign_form = CampaignUploadForm(
            data={"title": "Test", "purpose": "appointment", "template": template.pk},
            files={"csv_file": SimpleUploadedFile("test.csv", b"Patient Name,Patient Mobile\n")},
            user=self.user,
        )
        self.assertTrue(campaign_form.is_valid(), campaign_form.errors)


class TenantMigrationUpgradeTests(TransactionTestCase):
    reset_sequences = True

    def test_existing_prototype_data_is_backfilled(self):
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        old_targets = [
            target
            for target in latest_targets
            if target[0] not in {"account", "rasel"}
        ] + [("account", "0001_initial"), ("rasel", "0001_initial")]
        executor.migrate(old_targets)

        old_apps = executor.loader.project_state(old_targets).apps
        User = old_apps.get_model("account", "CustomUser")
        Profile = old_apps.get_model("account", "UserProfile")
        Contact = old_apps.get_model("rasel", "Contact")
        Template = old_apps.get_model("rasel", "MessageTemplate")
        AppointmentList = old_apps.get_model("rasel", "AppointmentsList")
        Appointment = old_apps.get_model("rasel", "Appointment")
        AssignedMessage = old_apps.get_model("rasel", "AssignedMessage")

        user = User.objects.create(username="legacy", email="legacy@example.com")
        Profile.objects.create(user=user, role="Admin")
        template = Template.objects.create(user=user, category="Legacy reminder", content="Hello")
        appointment_list = AppointmentList.objects.create(title="Legacy list", author=user)
        appointment_list.message_selected.add(template)
        contact = Contact.objects.create(
            name="Legacy Patient", phone_number="+971500000010", file_number="MR-10"
        )
        appointment = Appointment.objects.create(
            contact=contact,
            appointments_list=appointment_list,
            doctor_name="Dr Legacy",
            appointment_date=datetime.date(2026, 8, 12),
            appointment_time=datetime.time(10, 0),
            appointment_status="pending",
        )
        AssignedMessage.objects.create(
            appointment=appointment,
            message_template=template,
            custom_message="Legacy rendered message",
        )

        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            new_apps = executor.loader.project_state(
                executor.loader.graph.leaf_nodes()
            ).apps
            NewUser = new_apps.get_model("account", "CustomUser")
            Campaign = new_apps.get_model("rasel", "Campaign")
            CampaignItem = new_apps.get_model("rasel", "CampaignItem")
            CampaignMessage = new_apps.get_model("rasel", "CampaignMessage")

            migrated_user = NewUser.objects.get(email="legacy@example.com")
            self.assertIsNotNone(migrated_user.organization_id)
            self.assertEqual(Campaign.objects.get().organization_id, migrated_user.organization_id)
            item = CampaignItem.objects.get()
            self.assertEqual(item.appointment_status, "booked")
            self.assertEqual(item.patient_name_snapshot, "Legacy Patient")
            self.assertEqual(item.mrn_snapshot, "MR-10")
            self.assertEqual(CampaignMessage.objects.get().rendered_content, "Legacy rendered message")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
