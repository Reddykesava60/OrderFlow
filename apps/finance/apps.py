from django.apps import AppConfig

class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"

    def ready(self):
        from shared.event_bus import event_bus
        from apps.payments.use_cases import OrderPaidEvent
        from .handlers import handle_order_paid
        
        event_bus.subscribe(OrderPaidEvent, handle_order_paid)
