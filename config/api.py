from ninja import NinjaAPI
from django.core.exceptions import ValidationError

api = NinjaAPI(
    title="Order-Flow Greenfield API",
    version="2.0.0",
    description="Greenfield modular monolith API",
)

@api.exception_handler(ValueError)
def value_error_handler(request, exc):
    return api.create_response(request, {"detail": str(exc)}, status=400)

@api.exception_handler(ValidationError)
def django_validation_error_handler(request, exc):
    return api.create_response(request, {"detail": exc.messages}, status=400)

from apps.sales.api import router as sales_router
from apps.payments.api import router as payments_router

api.add_router("/sales", sales_router)
api.add_router("/payments", payments_router)
