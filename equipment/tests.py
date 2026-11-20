from unittest.mock import patch
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import TestCase
from rest_framework.test import APIClient

from . import services
from .models import Equipment, Reservation, ReservationEvent


class ReservationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('student_a', password='test-only-password-a')
        cls.other = get_user_model().objects.create_user('student_b', password='test-only-password-b')
        cls.laptop = Equipment.objects.create(name='Ноутбук', inventory_number='НБ-001', category='Ноутбуки')
        cls.projector = Equipment.objects.create(name='Проектор', inventory_number='ПР-001', category='Проекторы')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make(self, equipment=None, actor=None):
        return services.create_reservation(
            actor=actor or self.user, equipment=(equipment or self.laptop).pk,
            purpose='Подготовка презентации',
        )

    def operate(self, reservation, operation, actor=None):
        return services.perform_action(reservation.pk, actor=actor or self.user, action=operation)

    def url(self, reservation, suffix=''):
        return f'/api/reservations/{reservation.pk}/{suffix}'

    def snapshot(self, reservation):
        reservation.refresh_from_db()
        reservation.equipment.refresh_from_db()
        return (reservation.status, reservation.equipment_id, reservation.equipment.state,
                reservation.purpose, reservation.updated_at, reservation.deleted_at,
                list(reservation.events.values('id', 'action', 'from_status', 'to_status', 'details')))

    def test_create_and_history_contract(self):
        response = self.client.post('/api/reservations/', {
            'equipment': self.laptop.pk, 'purpose': '  Презентация  ',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), {
            'id', 'equipment', 'owner', 'purpose', 'status', 'created_at', 'updated_at',
        })
        self.assertEqual(response.data['purpose'], 'Презентация')
        self.assertEqual(response.data['owner']['id'], self.user.pk)
        self.assertEqual(response.data['equipment']['state'], 'available')
        reservation = Reservation.objects.get(pk=response.data['id'])
        history = self.client.get(self.url(reservation, 'history/'))
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data), 1)
        self.assertEqual(history.data[0]['action'], 'created')
        self.assertIsNone(history.data[0]['from_status'])
        self.assertEqual(history.data[0]['actor']['id'], self.user.pk)

    def test_full_lifecycle_and_equipment_release(self):
        reservation = self.make()
        for operation, expected_status, expected_state in [
            ('confirm', 'confirmed', 'reserved'),
            ('issue', 'issued', 'issued'),
            ('return', 'completed', 'available'),
        ]:
            response = self.client.post(self.url(reservation, f'{operation}/'), {}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['status'], expected_status)
            self.assertEqual(response.data['equipment']['state'], expected_state)
            reservation.refresh_from_db()
            reservation.equipment.refresh_from_db()
            self.assertEqual(reservation.status, expected_status)
            self.assertEqual(reservation.equipment.state, expected_state)
        self.assertEqual(list(reservation.events.values_list('action', flat=True)),
                         ['created', 'confirmed', 'issued', 'returned'])
        self.operate(self.make(actor=self.other), 'confirm', actor=self.other)

    def test_second_reservation_cannot_take_occupied_resource(self):
        first = self.make()
        second = self.make(actor=self.other)
        self.operate(first, 'confirm')
        before = self.snapshot(second)
        self.client.force_authenticate(self.other)
        response = self.client.post(self.url(second, 'confirm/'), {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(second), before)
        self.assertEqual(Reservation.objects.get(pk=first.pk).status, 'confirmed')

    def test_invalid_transitions_do_not_change_any_records(self):
        reservation = self.make()
        for operation in ['issue', 'return']:
            before = self.snapshot(reservation)
            response = self.client.post(self.url(reservation, f'{operation}/'), {}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.snapshot(reservation), before)
        for operation in ['confirm', 'issue', 'return']:
            self.operate(reservation, operation)
        for operation in ['confirm', 'issue', 'return', 'cancel']:
            before = self.snapshot(reservation)
            response = self.client.post(self.url(reservation, f'{operation}/'), {}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.snapshot(reservation), before)

    def test_cancel_new_does_not_release_someone_elses_equipment(self):
        first, second = self.make(), self.make(actor=self.other)
        self.operate(first, 'confirm')
        self.operate(second, 'cancel', actor=self.other)
        self.laptop.refresh_from_db()
        self.assertEqual(self.laptop.state, 'reserved')

    def test_cancel_confirmed_releases_resource_and_cannot_repeat(self):
        reservation = self.make()
        self.operate(reservation, 'confirm')
        self.operate(reservation, 'cancel')
        self.laptop.refresh_from_db()
        self.assertEqual(self.laptop.state, 'available')
        before = self.snapshot(reservation)
        response = self.client.post(self.url(reservation, 'cancel/'), {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(reservation), before)

    def test_issued_cannot_be_cancelled_or_deleted(self):
        reservation = self.make()
        self.operate(reservation, 'confirm')
        self.operate(reservation, 'issue')
        before = self.snapshot(reservation)
        self.assertEqual(self.client.post(self.url(reservation, 'cancel/'), {}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(self.url(reservation)).status_code, 400)
        self.assertEqual(self.snapshot(reservation), before)

    def test_edit_changes_fields_and_logs_old_and_new(self):
        reservation = self.make()
        response = self.client.patch(self.url(reservation), {
            'purpose': 'Семинар', 'equipment': self.projector.pk,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        reservation.refresh_from_db()
        self.assertEqual(reservation.equipment_id, self.projector.pk)
        event = reservation.events.last()
        self.assertEqual(event.action, 'updated')
        self.assertEqual(event.details['equipment'], {'old': self.laptop.pk, 'new': self.projector.pk})
        self.assertEqual(event.details['purpose']['new'], 'Семинар')
        self.assertEqual(event.from_status, event.to_status)

    def test_patch_same_value_does_not_create_event(self):
        reservation = self.make()
        before = self.snapshot(reservation)
        self.assertEqual(self.client.patch(self.url(reservation), {
            'purpose': reservation.purpose,
        }, format='json').status_code, 200)
        self.assertEqual(self.snapshot(reservation), before)

    def test_edit_and_delete_confirmed_are_forbidden(self):
        reservation = self.make()
        self.operate(reservation, 'confirm')
        before = self.snapshot(reservation)
        self.assertEqual(self.client.patch(self.url(reservation), {
            'equipment': self.projector.pk,
        }, format='json').status_code, 400)
        self.assertEqual(self.client.delete(self.url(reservation)).status_code, 400)
        self.assertEqual(self.snapshot(reservation), before)

    def test_service_failure_rolls_back_both_records_and_written_event(self):
        reservation = self.make()
        before = self.snapshot(reservation)
        real_event = services._event

        def write_then_fail(*args, **kwargs):
            real_event(*args, **kwargs)
            raise RuntimeError('Учебный сбой после создания события')

        with patch('equipment.services._event', side_effect=write_then_fail):
            with self.assertRaises(RuntimeError):
                self.operate(reservation, 'confirm')
        self.assertEqual(self.snapshot(reservation), before)

    def test_create_edit_and_delete_roll_back_when_event_fails(self):
        reservation = self.make()
        before = self.snapshot(reservation)
        with patch('equipment.services._event', side_effect=RuntimeError('Учебный сбой')):
            for operation in [
                lambda: self.make(equipment=self.projector),
                lambda: services.update_reservation(reservation.pk, actor=self.user, purpose='Изменено'),
                lambda: services.delete_reservation(reservation.pk, actor=self.user),
            ]:
                with self.assertRaises(RuntimeError):
                    operation()
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(self.snapshot(reservation), before)

    def test_all_foreign_endpoints_return_404(self):
        reservation = self.make(actor=self.other)
        before = self.snapshot(reservation)
        requests = [('get', '', None), ('patch', '', {'purpose': 'Подмена'}),
                    ('delete', '', None), ('get', 'history/', None)]
        requests += [('post', f'{operation}/', {}) for operation in ['confirm', 'issue', 'return', 'cancel']]
        for method, suffix, data in requests:
            with self.subTest(method=method, suffix=suffix):
                response = getattr(self.client, method)(self.url(reservation, suffix), data, format='json')
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get('/api/reservations/').data, [])
        self.assertEqual(self.snapshot(reservation), before)

    def test_services_also_reject_foreign_actor(self):
        reservation = self.make(actor=self.other)
        with self.assertRaises(Http404):
            self.operate(reservation, 'confirm')
        with self.assertRaises(Http404):
            services.delete_reservation(reservation.pk, actor=self.user)
        with self.assertRaises(Http404):
            services.update_reservation(reservation.pk, actor=self.user, purpose='Подмена')

    def test_logical_deletion_keeps_history_and_hides_all_endpoints(self):
        reservation = self.make()
        response = self.client.delete(self.url(reservation))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        reservation.refresh_from_db()
        self.assertIsNotNone(reservation.deleted_at)
        self.assertEqual(list(reservation.events.values_list('action', flat=True)), ['created', 'deleted'])
        self.assertEqual(self.client.get('/api/reservations/').data, [])
        self.assertEqual(self.client.get(self.url(reservation)).status_code, 404)
        self.assertEqual(self.client.get(self.url(reservation, 'history/')).status_code, 404)
        self.assertEqual(self.client.patch(self.url(reservation), {'purpose': 'Нет'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(self.url(reservation)).status_code, 404)
        for operation in ['confirm', 'issue', 'return', 'cancel']:
            self.assertEqual(self.client.post(self.url(reservation, f'{operation}/'), {}, format='json').status_code, 404)

    def test_completed_and_cancelled_can_be_deleted(self):
        for final in ['completed', 'cancelled']:
            reservation = self.make()
            operations = ['confirm', 'issue', 'return'] if final == 'completed' else ['cancel']
            for operation in operations:
                self.operate(reservation, operation)
            self.assertEqual(self.client.delete(self.url(reservation)).status_code, 204)

    def test_served_fields_cannot_be_submitted_even_unchanged(self):
        reservation = self.make()
        for field, value in {
            'id': reservation.pk, 'status': 'new', 'owner': self.other.pk,
            'created_at': '2026-11-13T10:00:00Z', 'updated_at': None, 'deleted_at': None,
            'actor': self.user.pk, 'state': 'available', 'unknown': 'value',
        }.items():
            for method in ['post', 'patch']:
                with self.subTest(field=field, method=method):
                    url = '/api/reservations/' if method == 'post' else self.url(reservation)
                    response = getattr(self.client, method)(url, {
                        'equipment': self.laptop.pk, 'purpose': 'Правильная строка', field: value,
                    }, format='json')
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(reservation.events.count(), 1)

    def test_invalid_input_is_rejected(self):
        invalid = [
            {}, {'equipment': self.laptop.pk}, {'purpose': 'Семинар'},
            {'equipment': 999999, 'purpose': 'Семинар'},
            {'equipment': -1, 'purpose': 'Семинар'},
            {'equipment': True, 'purpose': 'Семинар'},
            {'equipment': '1', 'purpose': 'Семинар'},
            {'equipment': 10 ** 30, 'purpose': 'Семинар'},
            {'equipment': self.laptop.pk, 'purpose': '   '},
            {'equipment': self.laptop.pk, 'purpose': 'a' * 501},
            {'equipment': self.laptop.pk, 'purpose': 123},
            {'equipment': self.laptop.pk, 'purpose': None}, [], 'not an object',
        ]
        for data in invalid:
            with self.subTest(data=str(data)[:80]):
                self.assertEqual(self.client.post('/api/reservations/', data, format='json').status_code, 400)
        response = self.client.post('/api/reservations/', '{', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Reservation.objects.exists())

    def test_empty_patch_and_nonempty_action_are_rejected(self):
        reservation = self.make()
        before = self.snapshot(reservation)
        self.assertEqual(self.client.patch(self.url(reservation), {}, format='json').status_code, 400)
        self.assertEqual(self.client.post(self.url(reservation, 'confirm/'), {
            'status': 'confirmed',
        }, format='json').status_code, 400)
        self.assertEqual(self.snapshot(reservation), before)

    def test_filters_work_separately_and_together_only_for_owner(self):
        laptop = self.make()
        projector = self.make(equipment=self.projector)
        self.operate(laptop, 'confirm')
        self.make(actor=self.other)
        for params, ids in [
            ({}, [projector.pk, laptop.pk]),
            ({'status': 'confirmed'}, [laptop.pk]),
            ({'category': 'Проекторы'}, [projector.pk]),
            ({'status': 'confirmed', 'category': 'Ноутбуки'}, [laptop.pk]),
            ({'status': 'completed', 'category': 'Ноутбуки'}, []),
        ]:
            response = self.client.get('/api/reservations/', params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row['id'] for row in response.data], ids)
        for params in [{'status': 'bogus'}, {'category': 'Неизвестно'}]:
            self.assertEqual(self.client.get('/api/reservations/', params).status_code, 400)

    def test_equipment_is_shared_but_cannot_be_written_through_api(self):
        self.assertEqual(len(self.client.get('/api/equipment/').data), 2)
        self.assertEqual(self.client.post('/api/equipment/', {}, format='json').status_code, 405)

    def test_put_is_disabled_and_data_survives_new_client(self):
        reservation = self.make()
        before = self.snapshot(reservation)
        self.assertEqual(self.client.put(self.url(reservation), {'status': 'issued'}, format='json').status_code, 405)
        self.assertEqual(self.snapshot(reservation), before)
        fresh_client = APIClient()
        fresh_client.force_authenticate(self.user)
        self.assertEqual(fresh_client.get(self.url(reservation)).data['purpose'], reservation.purpose)
        self.assertEqual(len(fresh_client.get(self.url(reservation, 'history/')).data), 1)

    def test_anonymous_and_session_without_csrf_cannot_change_data(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.get('/api/equipment/').status_code, 403)
        self.assertEqual(client.get('/api/reservations/').status_code, 403)
        client.force_login(self.user)
        self.assertEqual(client.post('/api/reservations/', {
            'equipment': self.laptop.pk, 'purpose': 'Семинар',
        }, format='json').status_code, 403)
        self.assertFalse(Reservation.objects.exists())

    def test_page_requires_login_and_provides_csrf_and_navigation(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/equipment/').status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get('/equipment/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reservation-form')
        self.assertContains(response, '/equipment/')
        self.assertIn('csrftoken', response.cookies)

    def test_physical_deletion_is_protected(self):
        reservation = self.make()
        with self.assertRaises(ProtectedError):
            reservation.delete()
        with self.assertRaises(ProtectedError):
            self.laptop.delete()
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_existing_portal_pages_still_render(self):
        self.client.force_login(self.user)
        for url in ['/', '/profile/', '/courses/', '/tickets/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_service_validation_rejects_bad_input(self):
        for data in [{'equipment': -1, 'purpose': 'Тест'},
                     {'equipment': self.laptop.pk, 'purpose': ' '}]:
            with self.assertRaises(ValidationError):
                services.create_reservation(actor=self.user, **data)
        self.assertFalse(Reservation.objects.exists())


class DemoCommandTests(TestCase):
    def test_demo_is_consistent_and_repeat_does_not_change_data(self):
        call_command('seed_equipment_demo', stdout=StringIO())
        self.assertEqual(Equipment.objects.count(), 4)
        self.assertSetEqual(set(Equipment.objects.values_list('inventory_number', flat=True)),
                            {'НБ-001', 'НБ-002', 'ПР-001', 'ПР-002'})
        self.assertEqual(Reservation.objects.count(), 7)
        users = get_user_model().objects.filter(username__in=['student_a', 'student_b'])
        self.assertEqual(users.count(), 2)
        for user in users:
            self.assertFalse(user.is_staff)
            self.assertFalse(user.has_usable_password())
        for device in Equipment.objects.all():
            active = device.reservations.filter(status__in=['confirmed', 'issued'])
            if device.state == 'available':
                self.assertFalse(active.exists())
            else:
                self.assertEqual(active.count(), 1)
                expected = 'confirmed' if device.state == 'reserved' else 'issued'
                self.assertEqual(active.get().status, expected)
        for reservation in Reservation.objects.all():
            self.assertGreater(reservation.events.count(), 0)
        before = ReservationEvent.objects.count()
        call_command('seed_equipment_demo', stdout=StringIO())
        self.assertEqual(Reservation.objects.count(), 7)
        self.assertEqual(ReservationEvent.objects.count(), before)

    def test_demo_does_not_take_over_existing_user(self):
        user = get_user_model().objects.create_user('student_a', password='existing-user-password')
        with self.assertRaises(CommandError):
            call_command('seed_equipment_demo', stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password('existing-user-password'))
        self.assertFalse(Equipment.objects.exists())
