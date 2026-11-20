from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EquipmentViewSet, ReservationViewSet, dashboard

router = DefaultRouter()
router.register('equipment', EquipmentViewSet, basename='equipment')
router.register('reservations', ReservationViewSet, basename='reservations')

urlpatterns = [
    path('equipment/', dashboard, name='equipment-dashboard'),
    path('api/', include(router.urls)),
]
