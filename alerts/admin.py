from django.contrib import admin
from .models import Events, AlertDescription

@admin.register(Events)
class FingerprintAdmin(admin.ModelAdmin):
    list_display = ('id', 'post_id', 'issue_id', 'status', 'acked_by', 'sms_text', 'created_at')
    search_fields = ('post_id', 'issue_id', 'status', 'acked_by')


@admin.register(AlertDescription)
class AlertDescriptionAdmin(admin.ModelAdmin):
    list_display = ('alertname', 'description_short', 'updated_at')
    search_fields = ('alertname', 'description')
    list_filter = ('created_at', 'updated_at')
    
    def description_short(self, obj):
        """Короткое описание для списка"""
        return obj.description[:100] + '...' if len(obj.description) > 100 else obj.description
    description_short.short_description = 'Описание'