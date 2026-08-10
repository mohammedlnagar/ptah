import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def backfill_tenant_data(apps, schema_editor):
    Organization = apps.get_model("account", "Organization")
    Contact = apps.get_model("rasel", "Contact")
    Doctor = apps.get_model("rasel", "Doctor")
    MessageTemplate = apps.get_model("rasel", "MessageTemplate")
    Campaign = apps.get_model("rasel", "Campaign")
    CampaignItem = apps.get_model("rasel", "CampaignItem")
    CampaignMessage = apps.get_model("rasel", "CampaignMessage")

    fallback = Organization.objects.get(slug="legacy-organization")
    now = django.utils.timezone.now()

    for template in MessageTemplate.objects.select_related("created_by"):
        template.organization_id = template.created_by.organization_id or fallback.id
        template.approval_status = "approved"
        template.approved_by_id = template.created_by_id
        template.approved_at = now
        template.save(
            update_fields=(
                "organization",
                "approval_status",
                "approved_by",
                "approved_at",
            )
        )

    for campaign in Campaign.objects.select_related("created_by").order_by("pk"):
        organization_id = campaign.created_by.organization_id or fallback.id
        campaign.organization_id = organization_id
        campaign.purpose = "appointment"
        campaign.status = "active"
        selected_template = campaign.message_selected.order_by("pk").first()
        campaign.template_id = selected_template.pk if selected_template else None
        campaign.save(
            update_fields=("organization", "purpose", "status", "template")
        )

        for row_number, item in enumerate(
            CampaignItem.objects.filter(campaign_id=campaign.pk)
            .select_related("contact")
            .order_by("pk"),
            start=1,
        ):
            contact = item.contact
            if contact.organization_id is None:
                contact.organization_id = organization_id
                contact.save(update_fields=("organization",))
            elif contact.organization_id != organization_id:
                contact = Contact.objects.create(
                    organization_id=organization_id,
                    name=contact.name,
                    phone_number=contact.phone_number,
                    mrn=contact.mrn,
                )
                item.contact_id = contact.pk

            doctor_name = (item.doctor_name_snapshot or "").strip()
            doctor = None
            if doctor_name:
                doctor, _ = Doctor.objects.get_or_create(
                    organization_id=organization_id,
                    name=doctor_name,
                    defaults={"is_active": True},
                )

            old_status = (item.appointment_status or "").strip().lower()
            if old_status in {"confirmed"}:
                normalized_status = "confirmed"
            elif old_status in {"cancelled", "canceled"}:
                normalized_status = "cancelled"
            else:
                normalized_status = "booked"

            item.organization_id = organization_id
            item.doctor_id = doctor.pk if doctor else None
            item.row_number = row_number
            item.patient_name_snapshot = contact.name
            item.phone_number_snapshot = contact.phone_number
            item.mrn_snapshot = contact.mrn or ""
            item.doctor_name_snapshot = doctor_name
            item.appointment_remarks = item.appointment_remarks or ""
            item.appointment_status = normalized_status
            item.save()

    Contact.objects.filter(organization__isnull=True).update(organization=fallback)

    for item in CampaignItem.objects.select_related("campaign"):
        messages = list(
            CampaignMessage.objects.filter(campaign_item_id=item.pk).order_by("pk")
        )
        for position, message in enumerate(messages):
            if position:
                message.delete()
                continue
            message.organization_id = item.organization_id
            message.rendered_content = message.rendered_content or ""
            old_status = (message.status or "").lower()
            message.status = {
                "sent": "sent",
                "ignored": "skipped",
            }.get(old_status, "pending")
            message.save()


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0002_tenant_foundation"),
        ("rasel", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(old_name="AppointmentsList", new_name="Campaign"),
        migrations.RenameModel(old_name="Appointment", new_name="CampaignItem"),
        migrations.RenameModel(old_name="AssignedMessage", new_name="CampaignMessage"),
        migrations.RenameField(model_name="contact", old_name="file_number", new_name="mrn"),
        migrations.RenameField(model_name="messagetemplate", old_name="category", new_name="name"),
        migrations.RenameField(model_name="messagetemplate", old_name="user", new_name="created_by"),
        migrations.RenameField(model_name="campaign", old_name="author", new_name="created_by"),
        migrations.RenameField(model_name="campaign", old_name="created_date", new_name="created_at"),
        migrations.RenameField(model_name="campaign", old_name="updated_date", new_name="updated_at"),
        migrations.RenameField(model_name="campaignitem", old_name="appointments_list", new_name="campaign"),
        migrations.RenameField(model_name="campaignitem", old_name="doctor_name", new_name="doctor_name_snapshot"),
        migrations.RenameField(model_name="campaignmessage", old_name="appointment", new_name="campaign_item"),
        migrations.RenameField(model_name="campaignmessage", old_name="message_template", new_name="template"),
        migrations.RenameField(model_name="campaignmessage", old_name="custom_message", new_name="rendered_content"),
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=150)),
                ("code", models.CharField(blank=True, max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.CreateModel(
            name="Doctor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=230)),
                ("code", models.CharField(blank=True, max_length=100)),
                ("phone_number", models.CharField(blank=True, max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("department", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="doctors", to="rasel.department")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.CreateModel(
            name="ImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("purpose", models.CharField(choices=[("appointment", "Appointment reminders"), ("marketing", "Marketing")], max_length=20)),
                ("original_filename", models.CharField(max_length=255)),
                ("source_file", models.FileField(blank=True, upload_to="imports/%Y/%m/")),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("uploaded", "Uploaded"), ("validated", "Validated"), ("imported", "Imported"), ("failed", "Failed"), ("replaced", "Replaced")], default="uploaded", max_length=20)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("imported_count", models.PositiveIntegerField(default=0)),
                ("error_count", models.PositiveIntegerField(default=0)),
                ("errors", models.JSONField(blank=True, default=list)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
                ("replaces", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="replacement", to="rasel.importbatch")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="imports", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddField(model_name="contact", name="created_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="contact", name="updated_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="contact", name="organization", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AddField(model_name="messagetemplate", name="created_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="messagetemplate", name="updated_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="messagetemplate", name="organization", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AddField(model_name="messagetemplate", name="purpose", field=models.CharField(choices=[("appointment", "Appointment reminder"), ("marketing", "Marketing"), ("general", "General")], default="appointment", max_length=20)),
        migrations.AddField(model_name="messagetemplate", name="approval_status", field=models.CharField(choices=[("draft", "Draft"), ("pending", "Pending approval"), ("approved", "Approved"), ("rejected", "Rejected")], default="draft", max_length=20)),
        migrations.AddField(model_name="messagetemplate", name="approved_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="messagetemplate", name="is_active", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="messagetemplate", name="approved_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_message_templates", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="campaign", name="organization", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AddField(model_name="campaign", name="purpose", field=models.CharField(choices=[("appointment", "Appointment reminders"), ("marketing", "Marketing")], default="appointment", max_length=20)),
        migrations.AddField(model_name="campaign", name="status", field=models.CharField(choices=[("draft", "Draft"), ("ready", "Ready"), ("active", "Active"), ("completed", "Completed"), ("archived", "Archived")], default="draft", max_length=20)),
        migrations.AddField(model_name="campaign", name="summary", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="campaign", name="import_batch", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="campaign", to="rasel.importbatch")),
        migrations.AddField(model_name="campaign", name="template", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="campaigns", to="rasel.messagetemplate")),
        migrations.AddField(model_name="campaignitem", name="created_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="campaignitem", name="updated_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="campaignitem", name="organization", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AddField(model_name="campaignitem", name="doctor", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="campaign_items", to="rasel.doctor")),
        migrations.AddField(model_name="campaignitem", name="row_number", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="campaignitem", name="patient_name_snapshot", field=models.CharField(default="", max_length=230), preserve_default=False),
        migrations.AddField(model_name="campaignitem", name="phone_number_snapshot", field=models.CharField(default="", max_length=20), preserve_default=False),
        migrations.AddField(model_name="campaignitem", name="mrn_snapshot", field=models.CharField(blank=True, max_length=230)),
        migrations.AddField(model_name="campaignitem", name="department_name_snapshot", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="campaignitem", name="raw_data", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="campaignmessage", name="created_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="campaignmessage", name="updated_at", field=models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField(model_name="campaignmessage", name="organization", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AddField(model_name="campaignmessage", name="opened_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="campaignmessage", name="sent_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sent_campaign_messages", to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(backfill_tenant_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name="campaign", name="message_selected"),
        migrations.AlterField(model_name="contact", name="phone_number", field=models.CharField(max_length=20)),
        migrations.AlterField(model_name="contact", name="mrn", field=models.CharField(blank=True, max_length=230, null=True)),
        migrations.AlterField(model_name="contact", name="created_at", field=models.DateTimeField(auto_now_add=True)),
        migrations.AlterField(model_name="contact", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(model_name="contact", name="organization", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AlterField(model_name="messagetemplate", name="created_at", field=models.DateTimeField(auto_now_add=True)),
        migrations.AlterField(model_name="messagetemplate", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(model_name="messagetemplate", name="organization", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AlterField(model_name="messagetemplate", name="created_by", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_message_templates", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="campaign", name="created_by", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="campaigns", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="campaign", name="organization", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AlterField(model_name="campaignitem", name="created_at", field=models.DateTimeField(auto_now_add=True)),
        migrations.AlterField(model_name="campaignitem", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(model_name="campaignitem", name="organization", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AlterField(model_name="campaignitem", name="campaign", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="rasel.campaign")),
        migrations.AlterField(model_name="campaignitem", name="contact", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="campaign_items", to="rasel.contact")),
        migrations.AlterField(model_name="campaignitem", name="row_number", field=models.PositiveIntegerField(default=1)),
        migrations.AlterField(model_name="campaignitem", name="appointment_remarks", field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name="campaignitem", name="appointment_status", field=models.CharField(blank=True, choices=[("booked", "Booked"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")], max_length=20, null=True)),
        migrations.AlterField(model_name="campaignitem", name="doctor_name_snapshot", field=models.CharField(blank=True, max_length=230)),
        migrations.AlterField(model_name="campaignmessage", name="created_at", field=models.DateTimeField(auto_now_add=True)),
        migrations.AlterField(model_name="campaignmessage", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(model_name="campaignmessage", name="organization", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
        migrations.AlterField(model_name="campaignmessage", name="campaign_item", field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="message", to="rasel.campaignitem")),
        migrations.AlterField(model_name="campaignmessage", name="template", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rendered_messages", to="rasel.messagetemplate")),
        migrations.AlterField(model_name="campaignmessage", name="rendered_content", field=models.TextField()),
        migrations.AlterField(model_name="campaignmessage", name="status", field=models.CharField(choices=[("pending", "Pending"), ("opened", "WhatsApp opened"), ("sent", "Marked sent"), ("skipped", "Skipped")], default="pending", max_length=10)),
        migrations.CreateModel(
            name="DoctorSummary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rendered_content", models.TextField()),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("opened", "WhatsApp opened"), ("sent", "Marked sent")], default="draft", max_length=10)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="doctor_summaries", to="rasel.campaign")),
                ("doctor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="summaries", to="rasel.doctor")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="account.organization")),
                ("sent_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sent_doctor_summaries", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterModelOptions(name="campaign", options={"ordering": ("-created_at",)}),
        migrations.AlterModelOptions(name="campaignitem", options={"ordering": ("row_number", "id")}),
        migrations.AlterModelOptions(name="contact", options={"ordering": ("name",)}),
        migrations.AlterModelOptions(name="messagetemplate", options={"ordering": ("name",), "permissions": [("approve_messagetemplate", "Can approve message templates")]}),
        migrations.AddConstraint(model_name="department", constraint=models.UniqueConstraint(fields=("organization", "name"), name="unique_department_name_per_org")),
        migrations.AddConstraint(model_name="department", constraint=models.UniqueConstraint(condition=~Q(code=""), fields=("organization", "code"), name="unique_department_code_per_org")),
        migrations.AddConstraint(model_name="doctor", constraint=models.UniqueConstraint(condition=~Q(code=""), fields=("organization", "code"), name="unique_doctor_code_per_org")),
        migrations.AddConstraint(model_name="contact", constraint=models.UniqueConstraint(fields=("organization", "phone_number"), name="unique_contact_phone_per_org")),
        migrations.AddConstraint(model_name="contact", constraint=models.UniqueConstraint(condition=Q(mrn__isnull=False) & ~Q(mrn=""), fields=("organization", "mrn"), name="unique_contact_mrn_per_org")),
        migrations.AddConstraint(model_name="messagetemplate", constraint=models.UniqueConstraint(fields=("organization", "name"), name="unique_template_name_per_org")),
        migrations.AddConstraint(model_name="campaignitem", constraint=models.UniqueConstraint(fields=("campaign", "row_number"), name="unique_campaign_row")),
        migrations.AddConstraint(model_name="doctorsummary", constraint=models.UniqueConstraint(fields=("campaign", "doctor"), name="unique_doctor_summary")),
        migrations.AddIndex(model_name="doctor", index=models.Index(fields=["organization", "name"], name="doctor_org_name_idx")),
        migrations.AddIndex(model_name="contact", index=models.Index(fields=["organization", "name"], name="contact_org_name_idx")),
        migrations.AddIndex(model_name="contact", index=models.Index(fields=["organization", "mrn"], name="contact_org_mrn_idx")),
        migrations.AddIndex(model_name="importbatch", index=models.Index(fields=["organization", "purpose", "status"], name="import_org_purpose_idx")),
        migrations.AddIndex(model_name="campaign", index=models.Index(fields=["organization", "purpose", "status"], name="campaign_org_status_idx")),
        migrations.AddIndex(model_name="campaign", index=models.Index(fields=["organization", "created_at"], name="campaign_org_created_idx")),
        migrations.AddIndex(model_name="campaignitem", index=models.Index(fields=["organization", "appointment_date"], name="item_org_date_idx")),
        migrations.AddIndex(model_name="campaignitem", index=models.Index(fields=["organization", "appointment_status"], name="item_org_appt_status_idx")),
        migrations.AddIndex(model_name="campaignitem", index=models.Index(fields=["organization", "doctor_name_snapshot"], name="item_org_doctor_idx")),
        migrations.AddIndex(model_name="campaignitem", index=models.Index(fields=["organization", "phone_number_snapshot"], name="item_org_phone_idx")),
        migrations.AddIndex(model_name="campaignitem", index=models.Index(fields=["organization", "mrn_snapshot"], name="item_org_mrn_idx")),
        migrations.AddIndex(model_name="campaignmessage", index=models.Index(fields=["organization", "status"], name="message_org_status_idx")),
    ]
