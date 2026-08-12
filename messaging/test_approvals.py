"""Template approval workflow: submit, approve, reject."""

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from common.test_utils import make_organization, make_template, make_user
from messaging.models import MessageTemplate, MessageTemplateRevision
from messaging.services import create_template_revision


def member(organization, role, email):
    user = make_user(organization, email=email, password="test-password-123")
    user.groups.add(Group.objects.get(name=role))
    return user


class ApprovalWorkflowTests(TestCase):
    def setUp(self):
        self.organization = make_organization()
        self.operator = member(self.organization, "Operator", "operator@example.com")
        self.approver = member(self.organization, "Approver", "approver@example.com")
        self.template = make_template(
            self.organization, created_by=self.operator, name="Reminder"
        )
        self.revision = create_template_revision(
            template=self.template,
            user=self.operator,
            content="Hello #patient_name",
        )

    def test_a_new_revision_starts_as_a_draft(self):
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.DRAFT,
        )

    def test_an_author_can_submit_a_draft_for_review(self):
        self.client.force_login(self.operator)

        response = self.client.post(
            reverse("submit_template", args=[self.revision.pk])
        )

        self.assertRedirects(response, reverse("template_approvals"))
        self.revision.refresh_from_db()
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.PENDING,
        )

    def test_an_operator_cannot_approve(self):
        self.revision.approval_status = MessageTemplateRevision.ApprovalStatus.PENDING
        self.revision.save(update_fields=("approval_status",))
        self.client.force_login(self.operator)

        response = self.client.post(
            reverse("approve_template", args=[self.revision.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.revision.refresh_from_db()
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.PENDING,
        )

    def test_an_approver_can_approve(self):
        self.revision.approval_status = MessageTemplateRevision.ApprovalStatus.PENDING
        self.revision.save(update_fields=("approval_status",))
        self.client.force_login(self.approver)

        self.client.post(reverse("approve_template", args=[self.revision.pk]))

        self.revision.refresh_from_db()
        self.template.refresh_from_db()
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.APPROVED,
        )
        self.assertEqual(self.revision.approved_by, self.approver)
        self.assertEqual(
            self.template.approval_status, MessageTemplate.ApprovalStatus.APPROVED
        )

    def test_rejecting_records_the_reason_and_returns_it_to_the_author(self):
        self.revision.approval_status = MessageTemplateRevision.ApprovalStatus.PENDING
        self.revision.save(update_fields=("approval_status",))
        self.client.force_login(self.approver)

        self.client.post(
            reverse("reject_template", args=[self.revision.pk]),
            {"reason": "Add the clinic name."},
        )

        self.revision.refresh_from_db()
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.REJECTED,
        )
        self.assertEqual(self.revision.rejection_reason, "Add the clinic name.")

    def test_a_rejected_revision_can_be_resubmitted(self):
        self.revision.approval_status = MessageTemplateRevision.ApprovalStatus.REJECTED
        self.revision.rejection_reason = "Needs work"
        self.revision.save(update_fields=("approval_status", "rejection_reason"))
        self.client.force_login(self.operator)

        self.client.post(reverse("submit_template", args=[self.revision.pk]))

        self.revision.refresh_from_db()
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.PENDING,
        )
        self.assertEqual(self.revision.rejection_reason, "")

    def test_an_approved_revision_cannot_be_rejected(self):
        self.revision.approval_status = MessageTemplateRevision.ApprovalStatus.PENDING
        self.revision.save(update_fields=("approval_status",))
        self.client.force_login(self.approver)
        self.client.post(reverse("approve_template", args=[self.revision.pk]))

        self.client.post(reverse("reject_template", args=[self.revision.pk]))

        self.revision.refresh_from_db()
        self.assertEqual(
            self.revision.approval_status,
            MessageTemplateRevision.ApprovalStatus.APPROVED,
        )

    def test_the_queue_groups_revisions_by_state(self):
        self.client.force_login(self.approver)

        response = self.client.get(reverse("template_approvals"))

        self.assertIn(self.revision, response.context["drafts"])
        self.assertEqual(response.context["awaiting_review"], [])
        self.assertTrue(response.context["can_approve"])

    def test_revisions_from_other_organizations_are_hidden(self):
        other = make_organization()
        other_author = member(other, "Operator", "other@example.com")
        other_template = make_template(other, created_by=other_author, name="Theirs")
        other_revision = create_template_revision(
            template=other_template, user=other_author, content="Hi"
        )
        self.client.force_login(self.approver)

        response = self.client.get(reverse("template_approvals"))

        self.assertNotIn(other_revision, response.context["drafts"])

    def test_a_revision_from_another_organization_cannot_be_approved(self):
        other = make_organization()
        other_author = member(other, "Operator", "other@example.com")
        other_template = make_template(other, created_by=other_author, name="Theirs")
        other_revision = create_template_revision(
            template=other_template, user=other_author, content="Hi"
        )
        self.client.force_login(self.approver)

        response = self.client.post(
            reverse("approve_template", args=[other_revision.pk])
        )

        self.assertEqual(response.status_code, 404)
