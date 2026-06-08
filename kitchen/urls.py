# kitchen/urls.py
from django.urls import path
from . import views

app_name = 'kitchen'

urlpatterns = [
    # KDS shell page
    path('kds/',                                views.KDSView.as_view(),        name='kds'),
    # Poll endpoint — Alpine.js calls this every 10s
    path('kds/poll/',                           views.KDSPollView.as_view(),    name='poll'),
    # Actions
    path('order/<uuid:order_id>/start-prep/',   views.StartPrepView.as_view(),  name='start_prep'),
    path('item/<uuid:item_id>/start-prep/',      views.StartItemPrepView.as_view(), name='start_item_prep'),
    path('addon/<uuid:addon_id>/start-prep/',    views.StartAddOnPrepView.as_view(), name='start_addon_prep'),
    path('item/<uuid:item_id>/complete/',        views.CompleteItemView.as_view(),name='complete_item'),
    path('addon/<uuid:addon_id>/complete/',      views.CompleteAddOnView.as_view(), name='complete_addon'),
    path('order/<uuid:order_id>/complete-all/', views.CompleteAllView.as_view(), name='complete_all'),
    path('cash/<uuid:order_id>/collect/',        views.CashCollectView.as_view(), name='cash_collect'),
]
