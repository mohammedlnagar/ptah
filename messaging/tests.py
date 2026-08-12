from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from common.test_utils import (
    make_campaign,
    make_campaign_item,
    make_campaign_message,
    make_organization,
    make_revision,
    make_template,
    make_user,
)
from messaging.models import (
    CampaignMessage,
    MessageTemplate,
    MessageTemplateRevision,
)


class MessageTemplateTests(TestCase):
    def test_defaults_to_a_draft_appointment_template(self):
        template = make_template(make_organization())

        self.assertEqual(template.purpose, MessageTemplate.Purpose.APPOINTMENT)
        self.assertEqual(template.approval_status, MessageTemplate.ApprovalStatus.DRAFT)
        self.assertTrue(template.is_active)

    def test_rejects_an_author_from_another_organization(self):
        organization = make_organization()
        outsider = make_user(make_organization())
        template = MessageTemplate(
            organization=organization,
            created_by=outsider,
            name="Reminder",
            content="Hello #patient_name",
        )

        with self.assertRaises(ValidationError):
            template.full_clean()

    def test_scoped_to_the_owning_organization(self):
        organization = make_organization()
        mine = make_template(organization)
        theirs = make_template(make_organization())

        results = MessageTemplate.objects.for_organization(organization)

        self.assertIn(mine, results)
        self.assertNotIn(theirs, results)


class ApprovedRevisionImmutabilityTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.template = make_template(self.organization)
        self.approver = self.template.created_by
        self.revision = make_revision(
            self.template,
            approval_status=MessageTemplateRevision.ApprovalStatus.APPROVED,
            approved_by=self.template.created_by,
            approved_at=timezone.now(),
        )

    def test_clean_rejects_editing_approved_content(self):
        self.revision.content = "Tampered content"

        with self.assertRaises(ValidationError):
            self.revision.full_clean()

    def test_save_rejects_editing_approved_content_without_full_clean(self):
        # A bare save() must not be able to bypass the rule; there is no
        # database constraint that can express it.
        self.revision.content = "Tampered content"

        with self.assertRaises(ValidationError):
            self.revision.save()

    def test_save_rejects_a_targeted_content_update(self):
        self.revision.content = "Tampered content"

        with self.assertRaises(ValidationError):
            self.revision.save(update_fields=("content",))

    def test_unrelated_fields_can_still_be_updated(self):
        self.revision.is_current = False
        self.revision.save(update_fields=("is_current", "updated_at"))

        self.revision.refresh_from_db()
        self.assertFalse(self.revision.is_current)

    def test_draft_revisions_remain_editable(self):
        draft = make_revision(self.template, version=2, is_current=False)
        draft.content = "Reworded draft"
        draft.save()

        draft.refresh_from_db()
        self.assertEqual(draft.content, "Reworded draft")

    def test_approved_revisions_require_an_approver(self):
        revision = MessageTemplateRevision(
            organization=self.organization,
            template=self.template,
            version=3,
            content="Some content",
            created_by=self.template.created_by,
            approval_status=MessageTemplateRevision.ApprovalStatus.APPROVED,
            is_current=False,
        )

        with self.assertRaises(ValidationError):
            revision.full_clean()


class CampaignMessageTests(TestCase):
    def test_defaults_to_pending(self):
        organization = make_organization()
        campaign = make_campaign(organization)
        item = make_campaign_item(campaign)

        message = make_campaign_message(item)

        self.assertEqual(message.status, CampaignMessage.Status.PENDING)

    def test_sent_status_uses_the_explicit_operator_value(self):
        self.assertEqual(CampaignMessage.Status.SENT, "operator_marked_sent")

    def test_scoped_to_the_owning_organization(self):
        organization = make_organization()
        mine = make_campaign_message(make_campaign_item(make_campaign(organization)))
        other_org = make_organization()
        theirs = make_campaign_message(make_campaign_item(make_campaign(other_org)))

        results = CampaignMessage.objects.for_organization(organization)

        self.assertIn(mine, results)
        self.assertNotIn(theirs, results)
