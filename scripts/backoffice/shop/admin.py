from django.contrib import admin

from .models import Customer, Order


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "city")
    search_fields = ("name", "email")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "customer", "status", "total", "tracking")
    list_filter = ("status",)
    search_fields = ("number", "customer__name")
