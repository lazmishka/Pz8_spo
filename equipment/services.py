"""Бизнес-операции. Все изменения и их события сохраняются одной транзакцией."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .models import Equipment, Reservation, ReservationEvent


def _owned(reservation_id, actor):
    if not actor.is_authenticated:
        raise Http404
    try:
        return Reservation.objects.select_related('equipment', 'owner').get(
            pk=reservation_id, owner=actor, deleted_at__isnull=True,
        )
    except Reservation.DoesNotExist:
        raise Http404('Бронирование не найдено или недоступно.')


def _purpose(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
        raise ValidationError({'purpose': 'Укажите назначение длиной от 1 до 500 символов.'})
    return value.strip()


def _equipment(equipment_id):
    if isinstance(equipment_id, bool) or not isinstance(equipment_id, int) or equipment_id <= 0:
        raise ValidationError({'equipment': 'Укажите положительный целочисленный id.'})
    try:
        return Equipment.objects.get(pk=equipment_id)
    except Equipment.DoesNotExist:
        raise ValidationError({'equipment': 'Такого экземпляра оборудования нет.'})


def _event(reservation, actor, action, old_status, details=None):
    return ReservationEvent.objects.create(
        reservation=reservation, actor=actor, action=action,
        from_status=old_status, to_status=reservation.status, details=details or {},
    )


def _move_equipment(reservation, expected, target):
    updated = Equipment.objects.filter(pk=reservation.equipment_id, state=expected).update(state=target)
    if not updated:
        raise ValidationError('Оборудование уже занято или его состояние изменилось. Обновите данные.')


@transaction.atomic
def create_reservation(*, actor, equipment, purpose):
    if not actor.is_authenticated:
        raise Http404
    reservation = Reservation.objects.create(
        owner=actor, equipment=_equipment(equipment), purpose=_purpose(purpose),
    )
    _event(reservation, actor, ReservationEvent.Action.CREATED, None)
    return reservation


@transaction.atomic
def update_reservation(reservation_id, *, actor, **changes):
    reservation = _owned(reservation_id, actor)
    if not changes or set(changes) - {'equipment', 'purpose'}:
        raise ValidationError('Передайте только equipment и/или purpose.')
    if reservation.status != Reservation.Status.NEW:
        raise ValidationError('Редактировать можно только созданное бронирование.')
    details = {}
    if 'purpose' in changes:
        purpose = _purpose(changes['purpose'])
        if purpose != reservation.purpose:
            details['purpose'] = {'old': reservation.purpose, 'new': purpose}
            reservation.purpose = purpose
    if 'equipment' in changes:
        equipment = _equipment(changes['equipment'])
        if equipment.pk != reservation.equipment_id:
            details['equipment'] = {'old': reservation.equipment_id, 'new': equipment.pk}
            reservation.equipment = equipment
    if details:
        reservation.save(update_fields=('purpose', 'equipment', 'updated_at'))
        _event(reservation, actor, ReservationEvent.Action.UPDATED, reservation.status, details)
    return reservation


@transaction.atomic
def perform_action(reservation_id, *, actor, action):
    reservation = _owned(reservation_id, actor)
    status = Reservation.Status
    state = Equipment.State
    transitions = {
        ('confirm', status.NEW): (status.CONFIRMED, state.AVAILABLE, state.RESERVED, 'confirmed'),
        ('issue', status.CONFIRMED): (status.ISSUED, state.RESERVED, state.ISSUED, 'issued'),
        ('return', status.ISSUED): (status.COMPLETED, state.ISSUED, state.AVAILABLE, 'returned'),
        ('cancel', status.NEW): (status.CANCELLED, None, None, 'cancelled'),
        ('cancel', status.CONFIRMED): (status.CANCELLED, state.RESERVED, state.AVAILABLE, 'cancelled'),
    }
    transition = transitions.get((action, reservation.status))
    if transition is None:
        raise ValidationError('Недопустимое действие для текущего статуса бронирования.')
    target_status, expected, target_state, event_action = transition
    old_status = reservation.status
    if expected is not None:
        _move_equipment(reservation, expected, target_state)
    reservation.status = target_status
    reservation.save(update_fields=('status', 'updated_at'))
    _event(reservation, actor, event_action, old_status)
    # Сериализация должна видеть новое состояние связанного экземпляра.
    reservation.equipment.refresh_from_db()
    return reservation


@transaction.atomic
def delete_reservation(reservation_id, *, actor):
    reservation = _owned(reservation_id, actor)
    if reservation.status not in {
        Reservation.Status.NEW, Reservation.Status.COMPLETED, Reservation.Status.CANCELLED,
    }:
        raise ValidationError('Активную бронь нельзя удалить. Сначала отмените её или оформите возврат.')
    reservation.deleted_at = timezone.now()
    reservation.save(update_fields=('deleted_at', 'updated_at'))
    _event(reservation, actor, ReservationEvent.Action.DELETED, reservation.status)
