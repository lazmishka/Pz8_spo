from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DomainError
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import Equipment, Reservation
from .serializers import (
    ActionInputSerializer, EquipmentSerializer, ReservationEventSerializer,
    ReservationInputSerializer, ReservationSerializer,
)


@login_required
@ensure_csrf_cookie
def dashboard(request):
    return render(request, 'equipment/dashboard.html', {
        'reservation_statuses': Reservation.Status.choices,
    })


def call_service(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except DomainError as exc:
        data = exc.message_dict if hasattr(exc, 'message_dict') else {'non_field_errors': exc.messages}
        raise serializers.ValidationError(data) from exc


class EquipmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Equipment.objects.all()
    serializer_class = EquipmentSerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = None


class ReservationViewSet(viewsets.GenericViewSet):
    serializer_class = ReservationSerializer
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    pagination_class = None
    http_method_names = ('get', 'post', 'patch', 'delete', 'head', 'options')

    def get_queryset(self):
        # Фильтры списка не должны мешать проверке владельца в detail/actions.
        return Reservation.objects.filter(
            owner=self.request.user, deleted_at__isnull=True,
        ).select_related('equipment', 'owner')

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            raise Http404('Бронирование не найдено или недоступно.') from None

    def list(self, request):
        queryset = self.get_queryset()
        requested_status = request.query_params.get('status', '')
        category = request.query_params.get('category', '')
        errors = {}
        if requested_status and requested_status not in Reservation.Status.values:
            errors['status'] = ['Неизвестный статус бронирования.']
        if category and not Equipment.objects.filter(category=category).exists():
            errors['category'] = ['Неизвестная категория оборудования.']
        if errors:
            raise serializers.ValidationError(errors)
        if requested_status:
            queryset = queryset.filter(status=requested_status)
        if category:
            queryset = queryset.filter(equipment__category=category)
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        serializer = ReservationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = call_service(services.create_reservation, actor=request.user,
                                   **serializer.validated_data)
        return Response(self.get_serializer(reservation).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        reservation = self.get_object()
        serializer = ReservationInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        reservation = call_service(services.update_reservation, reservation.pk, actor=request.user,
                                   **serializer.validated_data)
        return Response(self.get_serializer(reservation).data)

    def destroy(self, request, pk=None):
        reservation = self.get_object()
        call_service(services.delete_reservation, reservation.pk, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _business_action(self, request, operation):
        reservation = self.get_object()
        serializer = ActionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = call_service(services.perform_action, reservation.pk,
                                   actor=request.user, action=operation)
        return Response(self.get_serializer(reservation).data)

    @action(detail=True, methods=('post',))
    def confirm(self, request, pk=None):
        return self._business_action(request, 'confirm')

    @action(detail=True, methods=('post',))
    def issue(self, request, pk=None):
        return self._business_action(request, 'issue')

    @action(detail=True, methods=('post',), url_path='return', url_name='return')
    def return_equipment(self, request, pk=None):
        return self._business_action(request, 'return')

    @action(detail=True, methods=('post',))
    def cancel(self, request, pk=None):
        return self._business_action(request, 'cancel')

    @action(detail=True, methods=('get',))
    def history(self, request, pk=None):
        reservation = self.get_object()
        events = reservation.events.select_related('actor')
        return Response(ReservationEventSerializer(events, many=True).data)
