from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import StudentProfile
from equipment import services
from equipment.models import Equipment, Reservation


class Command(BaseCommand):
    help = 'Создать учебные данные без паролей. Пароли задаются отдельно командой changepassword.'

    @transaction.atomic
    def handle(self, *args, **options):
        items = [
            ('Учебный ноутбук 1', 'НБ-001', 'Ноутбуки'),
            ('Учебный ноутбук 2', 'НБ-002', 'Ноутбуки'),
            ('Учебный проектор 1', 'ПР-001', 'Проекторы'),
            ('Учебный проектор 2', 'ПР-002', 'Проекторы'),
        ]
        numbers = [number for name, number, category in items]
        existing = Equipment.objects.filter(inventory_number__in=numbers)
        if existing.exists():
            if existing.count() == len(numbers):
                self.stdout.write('Демонстрационный справочник уже существует. Данные не изменены.')
                return
            raise CommandError('Найден неполный учебный набор. Существующие записи не изменены.')
        # Не занимать существующие аккаунты пользователя и не менять их права/пароли.
        user_model = get_user_model()
        if user_model.objects.filter(username__in=['student_a', 'student_b']).exists():
            raise CommandError('Аккаунты student_a/student_b уже существуют. Автоматическое наполнение отменено.')
        a = user_model.objects.create_user(username='student_a', password=None)
        b = user_model.objects.create_user(username='student_b', password=None)
        for user in [a, b]:
            StudentProfile.objects.create(user=user)
        devices = []
        for name, number, category in items:
            devices.append(Equipment.objects.create(
                name=name,
                category=category, inventory_number=number,
            ))

        def make(user, index, purpose, operations=()):
            reservation = services.create_reservation(actor=user, equipment=devices[index].pk, purpose=purpose)
            for operation in operations:
                services.perform_action(reservation.pk, actor=user, action=operation)
            return reservation

        make(a, 3, 'Учебный пример: завершённая презентация', ('confirm', 'issue', 'return'))
        make(a, 1, 'Учебный пример: отменённая подготовка', ('cancel',))
        make(a, 0, 'Подготовка презентации', ('confirm',))
        make(a, 1, 'Работа над учебным проектом')
        make(a, 3, 'Показ презентации на семинаре')
        make(b, 2, 'Выступление на семинаре', ('confirm', 'issue'))
        make(b, 0, 'Проверка запрета повторного резервирования')
        self.stdout.write(self.style.SUCCESS(
            f'Создано 4 экземпляра и {Reservation.objects.filter(owner__in=[a, b]).count()} бронирований. '
            'Аккаунты student_a/student_b пока без возможности входа. '
            'Задайте пароли: manage.py changepassword student_a и student_b.'
        ))
