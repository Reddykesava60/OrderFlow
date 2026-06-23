from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        csp = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if csp:
            header = (
                "Content-Security-Policy-Report-Only"
                if getattr(settings, "CONTENT_SECURITY_POLICY_REPORT_ONLY", True)
                else "Content-Security-Policy"
            )
            response.setdefault(header, csp)

        permissions_policy = getattr(settings, "PERMISSIONS_POLICY", "")
        if permissions_policy:
            response.setdefault("Permissions-Policy", permissions_policy)

        return response


class MustChangePasswordMiddleware:
    """
    Force staff/owner users with a temporary password to set a new one before
    reaching authenticated application pages.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "must_change_password", False):
            allowed_paths = {
                reverse("owner:change_password"),
                reverse("owner:logout"),
                settings.LOGOUT_REDIRECT_URL,
            }
            if not (
                request.path in allowed_paths
                or request.path.startswith(settings.STATIC_URL)
                or request.path.startswith("/admin/")
            ):
                return redirect("owner:change_password")

        return self.get_response(request)


class AdminMfaMiddleware:
    """
    Forces staff/admin users with mfa_enabled=True to complete the 2FA verification
    step before they can access any /admin/ pages.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith('/admin/') and request.user.is_authenticated and request.user.is_staff:
            exempt_paths = [
                reverse('admin_mfa_setup'),
                reverse('admin_mfa_verify'),
                reverse('admin:logout'),
            ]
            if path not in exempt_paths:
                if getattr(request.user, 'mfa_enabled', False) and not request.user.is_verified():
                    return redirect('admin_mfa_verify')
        return self.get_response(request)
