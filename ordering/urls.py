# ordering/urls.py
from django.urls import path
from . import views

app_name = 'ordering'

urlpatterns = [
    path('menu/<uuid:restaurant_id>/',            views.MenuByIdView.as_view(), name='menu_by_id'),
    path('<slug:slug>/',                          views.MenuView.as_view(),     name='menu'),
    path('<slug:slug>/checkout/',                 views.CheckoutView.as_view(), name='checkout'),
    path('<slug:slug>/receipt/<uuid:order_id>/',  views.ReceiptView.as_view(),  name='receipt'),
]