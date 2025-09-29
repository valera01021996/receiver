from django.contrib import admin
from .models import Fingerprint

@admin.register(Fingerprint)
class FingerprintAdmin(admin.ModelAdmin):
    list_display = ('id', 'post_id', 'issue_id', 'status', 'acked_by')
    search_fields = ('post_id', 'issue_id', 'status', 'acked_by')