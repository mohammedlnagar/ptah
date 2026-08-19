from unittest import mock

from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    """The probe the container platform uses to decide if a revision is live."""

    def test_it_reports_ok_when_the_database_answers(self):
        response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_it_needs_no_authentication(self):
        # A probe cannot log in, so this must stay reachable anonymously.
        response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 200)

    def test_it_reports_unhealthy_when_the_database_is_unreachable(self):
        with mock.patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=Exception("connection refused"),
        ):
            response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unhealthy"})

    def test_it_rejects_other_methods(self):
        response = self.client.post(reverse("healthz"))

        self.assertEqual(response.status_code, 405)
