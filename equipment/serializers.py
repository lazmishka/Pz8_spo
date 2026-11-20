from rest_framework import serializers

from .models import Equipment, Reservation, ReservationEvent


class StrictInputSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({'non_field_errors': ['Ожидается JSON-объект.']})
        forbidden = set(data) - set(self.fields)
        if forbidden:
            raise serializers.ValidationError({
                key: ['Поле нельзя передавать в этом запросе.'] for key in sorted(forbidden)
            })
        return super().to_internal_value(data)


class EquipmentIdField(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            raise serializers.ValidationError('Ожидается положительный целочисленный id.')
        return super().to_internal_value(data)


class ReservationInputSerializer(StrictInputSerializer):
    equipment = EquipmentIdField(min_value=1, max_value=9223372036854775807)
    purpose = serializers.CharField(min_length=1, max_length=500, trim_whitespace=True)

    def to_internal_value(self, data):
        if isinstance(data, dict) and 'purpose' in data and not isinstance(data['purpose'], str):
            raise serializers.ValidationError({'purpose': ['Ожидается строка.']})
        return super().to_internal_value(data)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('Передайте equipment и/или purpose.')
        return attrs


class ActionInputSerializer(StrictInputSerializer):
    pass


class UserSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, user):
        return user.get_full_name() or user.get_username()


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = ('id', 'name', 'inventory_number', 'category', 'state')
        read_only_fields = fields


class ReservationSerializer(serializers.ModelSerializer):
    equipment = EquipmentSerializer(read_only=True)
    owner = UserSummarySerializer(read_only=True)

    class Meta:
        model = Reservation
        fields = ('id', 'equipment', 'owner', 'purpose', 'status', 'created_at', 'updated_at')
        read_only_fields = fields


class ReservationEventSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True, allow_null=True)

    class Meta:
        model = ReservationEvent
        fields = ('id', 'reservation', 'actor', 'action', 'created_at',
                  'from_status', 'to_status', 'details')
        read_only_fields = fields
