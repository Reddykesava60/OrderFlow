# owner/urls.py
from django.urls import path
from . import views
from . import views_customers

app_name = 'owner'

urlpatterns = [
    # Auth
    path('login/', views.OwnerLoginView.as_view(), name='login'),
    path('logout/', views.SecureLogoutView.as_view(),                               name='logout'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),

    # Dashboard
    path('',                         views.DashboardView.as_view(),       name='dashboard'),
    path('orders/<uuid:order_id>/',  views.OwnerOrderReceiptView.as_view(), name='order_receipt'),
    # path('orders/<uuid:order_id>/api/json/', views.OwnerOrderReceiptJsonView.as_view(), name='order_receipt_json'),
    # path('orders/<uuid:order_id>/api/action/', views.OwnerOrderActionView.as_view(), name='order_action'),

    # Menu
    path('menu/',                    views.MenuView.as_view(),             name='menu'),
    path('menu/item/add/',           views.MenuItemCreateView.as_view(),   name='menu_add'),
    path('menu/item/<uuid:item_id>/edit/',   views.MenuItemEditView.as_view(),   name='menu_edit'),
    path('menu/item/<uuid:item_id>/delete/', views.MenuItemDeleteView.as_view(), name='menu_delete'),
    path('menu/toggle/<uuid:item_id>/',      views.ToggleAvailabilityView.as_view(), name='menu_toggle'),
    path('menu/addon/add/',          views.AddOnCreateView.as_view(),      name='addon_add'),
    path('menu/addon/<uuid:addon_id>/edit/', views.AddOnEditView.as_view(), name='addon_edit'),
    path('menu/addon/<uuid:addon_id>/toggle/', views.AddOnToggleView.as_view(), name='addon_toggle'),
    path('menu/category/add/',       views.ItemTypeCreateView.as_view(),   name='category_add'),
    path('staff-filters/', views.StaffFilterView.as_view(), name='staff_filters'),
    path('staff-filters/<uuid:filter_id>/edit/', views.StaffFilterEditView.as_view(), name='staff_filter_edit'),
    path('staff-filters/<uuid:filter_id>/delete/', views.StaffFilterDeleteView.as_view(), name='staff_filter_delete'),

    # Staff
    path('staff/',                           views.StaffView.as_view(),            name='staff'),
    path('staff/add/',                       views.StaffCreateView.as_view(),       name='staff_add'),
    path('staff/<int:user_id>/created/',     views.StaffCreatedView.as_view(),      name='staff_created'),
    path('staff/<int:user_id>/edit/',        views.StaffEditView.as_view(),         name='staff_edit'),
    path('staff/<int:user_id>/delete/',      views.StaffDeleteView.as_view(),       name='staff_delete'),
    path('staff/<int:user_id>/reset-pw/',    views.StaffResetPasswordView.as_view(),name='staff_reset_pw'),
    path('staff/<int:user_id>/toggle-permission/', views.StaffPermissionToggleView.as_view(), name='staff_toggle_permission'),

    # Customers
    path('customers/', views_customers.CustomerListView.as_view(), name='customers'),
    path('customers/api/', views_customers.CustomerListApiView.as_view(), name='customers_api'),
    path('customers/add/', views_customers.CustomerCreateView.as_view(), name='customer_add'),
    path('customers/<uuid:customer_id>/edit/', views_customers.CustomerEditView.as_view(), name='customer_edit'),
    path('customers/<uuid:customer_id>/payment/', views_customers.CustomerPaymentView.as_view(), name='customer_payment'),
    path('customers/<uuid:customer_id>/ledger/', views_customers.CustomerLedgerView.as_view(), name='customer_ledger'),
    path('customers/<uuid:customer_id>/pin/', views_customers.CustomerResetPinView.as_view(), name='customer_reset_pin'),

    # Config
    path('config/', views.ConfigView.as_view(), name='config'),
    path('config/qr-code/menu.png', views.MenuQrCodeDownloadView.as_view(), name='menu_qr_download'),

    # Reconciliation
    path('reconcile/', views.ReconcileView.as_view(), name='reconcile'),
]
