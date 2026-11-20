"""RUN_BROWSER_TESTS=1 .venv/bin/python manage.py test equipment.test_browser"""

import os
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client

from . import services
from .models import Equipment


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'Браузерные тесты запускаются отдельно')
class EquipmentBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright

        user = get_user_model().objects.create_user('browser_a', password='browser-test-password')
        other = get_user_model().objects.create_user('browser_b', password='browser-test-other-password')
        laptop = Equipment.objects.create(name='Ноутбук для теста', category='Ноутбуки', inventory_number='НБ-001')
        projector = Equipment.objects.create(name='Проектор для теста', category='Проекторы', inventory_number='ПР-001')
        self.reservation = services.create_reservation(actor=user, equipment=laptop.pk, purpose='Начальная запись')
        second = services.create_reservation(actor=user, equipment=projector.pk, purpose='Семинар')
        services.perform_action(second.pk, actor=user, action='confirm')
        self.foreign = services.create_reservation(actor=other, equipment=laptop.pk, purpose='Чужая запись')
        client = Client()
        client.force_login(user)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.context.add_cookies([{
            'name': settings.SESSION_COOKIE_NAME, 'value': cookie, 'url': self.live_server_url,
        }])
        self.page = self.context.new_page()
        self.errors = []
        self.api_responses = []
        self.page.on('response', lambda response: self.api_responses.append((response.status, response.url))
                     if '/api/' in response.url else None)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(f'{self.live_server_url}/equipment/')
        self.page.wait_for_function("document.querySelectorAll('.reservation-row').length === 2")

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()
        self.assertEqual(self.errors, [])
        super().tearDown()

    def select_initial(self):
        self.page.locator(f'[data-reservation-id="{self.reservation.pk}"]').click()
        self.page.wait_for_function("document.querySelector('#edit-reservation-form') || !document.querySelector('#load-error').hidden")
        self.assertEqual(self.page.locator('#load-error').inner_text(), '', self.api_responses)
        self.page.locator('#edit-reservation-form').wait_for()

    def wait_unlocked(self):
        self.page.wait_for_function("!document.querySelector('#refresh-all').disabled")

    def test_crud_transitions_history_and_reload(self):
        from playwright.sync_api import expect

        self.page.locator('#equipment-input').select_option(label='Ноутбук для теста · НБ-001 — Свободно')
        self.page.locator('#purpose-input').fill('Новая презентация')
        self.page.locator('#create-button').click()
        expect(self.page.locator('#operation-message')).to_contain_text('Бронирование создано')
        self.wait_unlocked()
        self.page.locator('#edit-purpose').fill('Исправленная презентация')
        self.page.locator('#edit-reservation-form button').click()
        self.wait_unlocked()
        expect(self.page.locator('#reservation-history')).to_contain_text('Редактирование')
        for action, expected in [('confirm', 'Подтверждено'), ('issue', 'Выдано'), ('return', 'Завершено')]:
            self.page.locator(f'#reservation-detail [data-action="{action}"]').click()
            self.wait_unlocked()
            expect(self.page.locator('#reservation-detail .badge')).to_have_text(expected)
        expect(self.page.locator('#reservation-history')).to_contain_text('Возврат')
        self.page.reload()
        row = self.page.locator('.reservation-row').filter(has_text='Исправленная презентация')
        row.click()
        expect(self.page.locator('#reservation-detail .badge')).to_have_text('Завершено')
        expect(self.page.locator('#reservation-history')).to_contain_text('Возврат')

    def test_delete_cancel_sends_no_request_then_confirm_removes(self):
        from playwright.sync_api import expect

        self.select_initial()
        deletes = []
        self.page.on('request', lambda request: deletes.append(request.url) if request.method == 'DELETE' else None)
        self.page.once('dialog', lambda dialog: dialog.dismiss())
        self.page.locator('[data-action="delete"]').click()
        expect(self.page.locator('.reservation-row')).to_have_count(2)
        self.assertEqual(deletes, [])
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.locator('[data-action="delete"]').click()
        self.wait_unlocked()
        expect(self.page.locator('.reservation-row')).to_have_count(1)
        expect(self.page.locator('#reservation-detail')).to_contain_text('Выберите запись')
        self.assertEqual(len(deletes), 1)

    def test_filters_send_both_parameters_and_show_empty_result(self):
        from playwright.sync_api import expect

        self.page.locator('#status-filter').select_option('confirmed')
        expect(self.page.locator('.reservation-row')).to_have_count(1)
        with self.page.expect_response(lambda response: '/api/reservations/?' in response.url and 'category=' in response.url) as result:
            self.page.locator('#category-filter').select_option('Ноутбуки')
        self.assertIn('status=confirmed', result.value.url)
        expect(self.page.locator('.reservation-row')).to_have_count(0)
        expect(self.page.locator('#reservation-list')).to_contain_text('бронирований нет')

    def test_400_is_shown_and_foreign_and_invalid_actions_are_rejected(self):
        from playwright.sync_api import expect

        self.page.locator('#equipment-input').select_option(label='Ноутбук для теста · НБ-001 — Свободно')
        self.page.locator('#purpose-input').fill('   ')
        self.page.locator('#create-button').click()
        expect(self.page.locator('#operation-message')).to_contain_text('Назначение')
        self.wait_unlocked()
        statuses = self.page.evaluate("""async ({own, foreign}) => {
            const headers = {'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value};
            const invalid = await fetch(`/api/reservations/${own}/issue/`, {method:'POST', headers, body:'{}'});
            const denied = await fetch(`/api/reservations/${foreign}/history/`);
            return [invalid.status, denied.status];
        }""", {'own': self.reservation.pk, 'foreign': self.foreign.pk})
        self.assertEqual(statuses, [400, 404])

    def test_server_and_network_errors_are_visible_and_recoverable(self):
        from playwright.sync_api import expect

        url = '**/api/reservations/?*'
        self.page.route(url, lambda route: route.fulfill(status=500, content_type='text/html', body='Failure'))
        self.page.locator('#refresh-all').click()
        expect(self.page.locator('#load-error')).to_contain_text('Сбой сервера')
        self.wait_unlocked()
        self.page.unroute(url)
        self.page.route(url, lambda route: route.abort())
        self.page.locator('#refresh-all').click()
        expect(self.page.locator('#load-error')).to_contain_text('Нет связи')
        self.wait_unlocked()
        self.page.unroute(url)
        self.page.route(url, lambda route: route.fulfill(status=200, content_type='text/html', body='Not JSON'))
        self.page.locator('#refresh-all').click()
        expect(self.page.locator('#load-error')).to_contain_text('не удалось прочитать')
        self.wait_unlocked()
        self.page.unroute(url)
        self.page.locator('#refresh-all').click()
        self.wait_unlocked()
        expect(self.page.locator('#load-error')).to_be_hidden()
        expect(self.page.locator('.reservation-row')).to_have_count(2)

    def test_403_message_and_safe_text_rendering(self):
        from playwright.sync_api import expect

        self.page.route('**/api/reservations/?*', lambda route: route.fulfill(
            status=403, content_type='application/json', body='{"detail": "Нет прав."}',
        ))
        self.page.locator('#refresh-all').click()
        expect(self.page.locator('#load-error')).to_contain_text('Нет доступа')
        self.wait_unlocked()
        self.page.unroute('**/api/reservations/?*')
        self.page.locator('#refresh-all').click()
        self.wait_unlocked()
        self.select_initial()
        payload = '<img src=x onerror="window.XSS_EXECUTED=true">'
        self.page.locator('#edit-purpose').fill(payload)
        self.page.locator('#edit-reservation-form button').click()
        self.wait_unlocked()
        expect(self.page.locator('#reservation-detail')).to_contain_text(payload)
        self.assertFalse(self.page.evaluate('Boolean(window.XSS_EXECUTED)'))
        self.assertEqual(self.page.locator('#reservation-detail img').count(), 0)

    def test_mutation_success_and_refresh_failure_are_not_confused(self):
        from playwright.sync_api import expect

        self.select_initial()
        self.page.route('**/api/reservations/?*', lambda route: route.fulfill(status=500, body='Failure'))
        self.page.locator('[data-action="confirm"]').click()
        expect(self.page.locator('#operation-message')).to_contain_text('выполнено')
        expect(self.page.locator('#load-error')).to_contain_text('Действие сохранено')
        self.wait_unlocked()
        self.page.unroute('**/api/reservations/?*')
        self.page.locator('#refresh-all').click()
        self.wait_unlocked()
        expect(self.page.locator('#reservation-detail .badge')).to_have_text('Подтверждено')

    def test_mobile_controls_fit_screen(self):
        from playwright.sync_api import expect

        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.select_initial()
        expect(self.page.locator('#edit-purpose')).to_be_visible()
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))

    def test_real_login_logout_and_second_users_visibility(self):
        from playwright.sync_api import expect

        self.context.clear_cookies()
        self.page.goto(f'{self.live_server_url}/accounts/login/')
        self.page.locator('[name="username"]').fill('browser_b')
        self.page.locator('[name="password"]').fill('browser-test-other-password')
        self.page.locator('button[type="submit"]').click()
        expect(self.page).to_have_url(f'{self.live_server_url}/equipment/')
        expect(self.page.locator('.reservation-row')).to_have_count(1)
        expect(self.page.locator('.reservation-row')).to_contain_text('Чужая запись')
        response_status = self.page.evaluate(
            'async (id) => (await fetch(`/api/reservations/${id}/`)).status', self.reservation.pk,
        )
        self.assertEqual(response_status, 404)
        self.page.locator('form[action="/accounts/logout/"] button').click()
        expect(self.page).to_have_url(f'{self.live_server_url}/accounts/login/')
        self.assertEqual(self.page.evaluate('async () => (await fetch("/api/reservations/")).status'), 403)
