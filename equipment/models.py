from django.conf import settings
from django.db import models


class Equipment(models.Model):
    class State(models.TextChoices):
        AVAILABLE = 'available', 'Свободно'
        RESERVED = 'reserved', 'Зарезервировано'
        ISSUED = 'issued', 'Выдано'

    name = models.CharField('Название', max_length=200)
    inventory_number = models.CharField('Инвентарный номер', max_length=80, unique=True)
    category = models.CharField('Категория', max_length=80)
    state = models.CharField('Состояние', max_length=12, choices=State.choices,
                             default=State.AVAILABLE)

    class Meta:
        ordering = ('category', 'name', 'inventory_number')
        verbose_name = 'экземпляр оборудования'
        verbose_name_plural = 'оборудование'

    def __str__(self):
        return f'{self.name} · {self.inventory_number}'


class Reservation(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Создано'
        CONFIRMED = 'confirmed', 'Подтверждено'
        ISSUED = 'issued', 'Выдано'
        COMPLETED = 'completed', 'Завершено'
        CANCELLED = 'cancelled', 'Отменено'

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT,
                                  related_name='reservations', verbose_name='Экземпляр')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name='equipment_reservations', verbose_name='Владелец')
    purpose = models.CharField('Назначение', max_length=500)
    status = models.CharField('Статус', max_length=12, choices=Status.choices,
                              default=Status.NEW)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Изменено', auto_now=True)
    deleted_at = models.DateTimeField('Удалено', null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        verbose_name = 'бронирование'
        verbose_name_plural = 'бронирования'
        constraints = [
            models.UniqueConstraint(
                fields=('equipment',),
                condition=models.Q(status__in=('confirmed', 'issued'), deleted_at__isnull=True),
                name='one_active_reservation_per_equipment',
            ),
        ]

    def __str__(self):
        return f'Бронирование №{self.pk} · {self.equipment}'


class ReservationEvent(models.Model):
    class Action(models.TextChoices):
        CREATED = 'created', 'Создание'
        UPDATED = 'updated', 'Редактирование'
        CONFIRMED = 'confirmed', 'Подтверждение'
        ISSUED = 'issued', 'Выдача'
        RETURNED = 'returned', 'Возврат'
        CANCELLED = 'cancelled', 'Отмена'
        DELETED = 'deleted', 'Удаление'

    reservation = models.ForeignKey(Reservation, on_delete=models.PROTECT,
                                    related_name='events', verbose_name='Бронирование')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, related_name='equipment_events', verbose_name='Инициатор')
    action = models.CharField('Действие', max_length=12, choices=Action.choices)
    created_at = models.DateTimeField('Время', auto_now_add=True)
    from_status = models.CharField('Прежний статус', max_length=12, null=True, blank=True)
    to_status = models.CharField('Новый статус', max_length=12)
    details = models.JSONField('Изменения', default=dict, blank=True)

    class Meta:
        ordering = ('created_at', 'pk')
        verbose_name = 'событие бронирования'
        verbose_name_plural = 'события бронирований'
