from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Category, Ticket


class TicketApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="student1",
            password="test-password-123",
        )
        self.other_user = user_model.objects.create_user(
            username="student2",
            password="test-password-456",
        )
        self.category = Category.objects.create(name="Техническая поддержка")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_ticket(self, owner=None, status=Ticket.Status.NEW):
        return Ticket.objects.create(
            title="Проблема с доступом",
            category=self.category,
            owner=owner or self.user,
            status=status,
        )

    def test_categories_are_returned_from_database(self):
        response = self.client.get("/api/categories/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["name"], self.category.name)

    def test_create_ticket_and_assign_current_user(self):
        response = self.client.post(
            "/api/tickets/",
            {
                "title": "Не работает вход",
                "category": self.category.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Ticket.Status.NEW)
        self.assertEqual(
            Ticket.objects.get(pk=response.data["id"]).owner,
            self.user,
        )

    def test_short_title_is_rejected_by_server(self):
        response = self.client.post(
            "/api/tickets/",
            {"title": "Нет", "category": self.category.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Ticket.objects.filter(title="Нет").exists())

    def test_valid_status_transition_is_allowed(self):
        ticket = self.make_ticket()

        response = self.client.patch(
            f"/api/tickets/{ticket.pk}/",
            {"status": Ticket.Status.PROGRESS},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROGRESS)

    def test_invalid_status_transition_is_rejected(self):
        ticket = self.make_ticket()

        response = self.client.patch(
            f"/api/tickets/{ticket.pk}/",
            {"status": Ticket.Status.DONE},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.NEW)

    def test_user_cannot_read_another_users_ticket(self):
        ticket = self.make_ticket(owner=self.other_user)

        response = self.client.get(f"/api/tickets/{ticket.pk}/")

        self.assertEqual(response.status_code, 404)

    def test_user_cannot_change_another_users_ticket(self):
        ticket = self.make_ticket(owner=self.other_user)

        response = self.client.patch(
            f"/api/tickets/{ticket.pk}/",
            {"status": Ticket.Status.PROGRESS},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.NEW)

    def test_user_cannot_delete_another_users_ticket(self):
        ticket = self.make_ticket(owner=self.other_user)

        response = self.client.delete(f"/api/tickets/{ticket.pk}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_user_can_delete_their_own_ticket(self):
        ticket = self.make_ticket()

        response = self.client.delete(f"/api/tickets/{ticket.pk}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Ticket.objects.filter(pk=ticket.pk).exists())
