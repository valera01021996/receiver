from django.contrib import admin
from .models import Events

@admin.register(Events)
class FingerprintAdmin(admin.ModelAdmin):
    list_display = ('id', 'post_id', 'issue_id', 'status', 'acked_by', 'sms_text', 'done')
    search_fields = ('post_id', 'issue_id', 'status', 'acked_by')