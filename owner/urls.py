# owner/urls.py
from django.urls import path
from .views import auth, dashboard, menu, reports, settings, staff
from . import views_customers

app_name = 'owner'

urlpatterns = [
    # Auth
    path('login/', auth.OwnerLoginView.as_view(), name='login'),
    path('logout/', auth.SecureLogoutView.as_view(),                               name='logout'),
    path('change-password/', auth.ChangePasswordView.as_view(), name='change_password'),
    path('mfa/setup/', auth.MfaSetupView.as_view(), name='mfa_setup'),
    path('mfa/verify/', auth.MfaVerifyView.as_view(), name='mfa_verify'),

    # Dashboard
    path('',                         dashboard.DashboardView.as_view(),       name='dashboard'),
    path('orders/<uuid:order_id>/',  reports.OwnerOrderReceiptView.as_view(), name='order_receipt'),

    # Menu
    path('menu/',                    menu.MenuView.as_view(),             name='menu'),
    path('menu/item/add/',           menu.MenuItemCreateView.as_view(),   name='menu_add'),
    path('menu/item/<uuid:item_id>/edit/',   menu.MenuItemEditView.as_view(),   name='menu_edit'),
    path('menu/item/<uuid:item_id>/delete/', menu.MenuItemDeleteView.as_view(), name='menu_delete'),
    path('menu/toggle/<uuid:item_id>/',      menu.ToggleAvailabilityView.as_view(), name='menu_toggle'),
    path('menu/addon/add/',          menu.AddOnCreateView.as_view(),      name='addon_add'),
    path('menu/addon/<uuid:addon_id>/edit/', menu.AddOnEditView.as_view(), name='addon_edit'),
    path('menu/addon/<uuid:addon_id>/toggle/', menu.AddOnToggleView.as_view(), name='addon_toggle'),
    path('menu/category/add/',       menu.ItemTypeCreateView.as_view(),   name='category_add'),
    path('menu/category/<uuid:category_id>/edit/', menu.ItemTypeEditView.as_view(), name='category_edit'),
    path('staff-filters/', staff.StaffFilterView.as_view(), name='staff_filters'),
    path('staff-filters/<uuid:filter_id>/edit/', staff.StaffFilterEditView.as_view(), name='staff_filter_edit'),
    path('staff-filters/<uuid:filter_id>/delete/', staff.StaffFilterDeleteView.as_view(), name='staff_filter_delete'),

    # Staff
    path('staff/',                           staff.StaffView.as_view(),            name='staff'),
    path('staff/add/',                       staff.StaffCreateView.as_view(),       name='staff_add'),
    path('staff/<int:user_id>/created/',     staff.StaffCreatedView.as_view(),      name='staff_created'),
    path('staff/<int:user_id>/edit/',        staff.StaffEditView.as_view(),         name='staff_edit'),
    path('staff/<int:user_id>/delete/',      staff.StaffDeleteView.as_view(),       name='staff_delete'),
    path('staff/<int:user_id>/reset-pw/',    staff.StaffResetPasswordView.as_view(),name='staff_reset_pw'),
    path('staff/<int:user_id>/toggle-permission/', staff.StaffPermissionToggleView.as_view(), name='staff_toggle_permission'),

    # Customers
    path('customers/', views_customers.CustomerListView.as_view(), name='customers'),
    path('customers/api/', views_customers.CustomerListApiView.as_view(), name='customers_api'),
    path('customers/<uuid:customer_id>/edit/', views_customers.CustomerEditView.as_view(), name='customer_edit'),
    path('customers/<uuid:customer_id>/payment/', views_customers.CustomerPaymentView.as_view(), name='customer_payment'),
    path('customers/<uuid:customer_id>/ledger/', views_customers.CustomerLedgerView.as_view(), name='customer_ledger'),
    path('customers/<uuid:customer_id>/pin/', views_customers.CustomerResetPinView.as_view(), name='customer_reset_pin'),

    # Config
    path('config/', settings.ConfigView.as_view(), name='config'),
    path('config/qr-code/menu.png', settings.MenuQrCodeDownloadView.as_view(), name='menu_qr_download'),

    # Reconciliation
    path('reconcile/', dashboard.ReconcileView.as_view(), name='reconcile'),
]
