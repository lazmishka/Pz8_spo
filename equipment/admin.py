from django.contrib import admin

from .models import Equipment, Reservation, ReservationEvent


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'inventory_number', 'category', 'state')
    list_filter = ('category', 'state')
    search_fields = ('name', 'inventory_number')
    readonly_fields = ('state',)


class AuditReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Reservation)
class ReservationAdmin(AuditReadOnlyAdmin):
    list_display = ('id', 'equipment', 'owner', 'status', 'deleted_at')
    list_filter = ('status',)


@admin.register(ReservationEvent)
class ReservationEventAdmin(AuditReadOnlyAdmin):
    list_display = ('reservation', 'action', 'actor', 'created_at')
    list_filter = ('action',)
