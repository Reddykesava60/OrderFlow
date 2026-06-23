import io
import base64
import qrcode
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import render, redirect
from django.views import View
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice


class AdminMfaMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class AdminMfaSetupView(AdminMfaMixin, View):
    def get(self, request):
        if not getattr(request.user, 'mfa_enabled', False):
            return redirect('admin:index')
        if request.user.is_verified():
            return redirect('admin:index')
        
        device, created = TOTPDevice.objects.get_or_create(user=request.user, name="default")
        
        qr_url = device.config_url
        img = qrcode.make(qr_url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        return render(request, 'admin/mfa_setup.html', {'qr_code': qr_b64, 'secret': device.key})

    def post(self, request):
        if not getattr(request.user, 'mfa_enabled', False):
            return redirect('admin:index')
        if request.user.is_verified():
            return redirect('admin:index')
            
        token = request.POST.get('token', '').strip()
        device = TOTPDevice.objects.filter(user=request.user).first()
        
        if not device:
            messages.error(request, "No device found.")
            return redirect('admin_mfa_setup')
            
        if device.verify_token(token):
            device.confirmed = True
            device.save()
            otp_login(request, device)
            return redirect('admin:index')
            
        messages.error(request, "Invalid token. Try again.")
        return redirect('admin_mfa_setup')


class AdminMfaVerifyView(AdminMfaMixin, View):
    def get(self, request):
        if not getattr(request.user, 'mfa_enabled', False):
            return redirect('admin:index')
        if request.user.is_verified():
            return redirect('admin:index')
        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        if not device:
            return redirect('admin_mfa_setup')
        return render(request, 'admin/mfa_verify.html')
        
    def post(self, request):
        if not getattr(request.user, 'mfa_enabled', False):
            return redirect('admin:index')
        if request.user.is_verified():
            return redirect('admin:index')
        token = request.POST.get('token', '').strip()
        device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        if not device:
            return redirect('admin_mfa_setup')
            
        if device.verify_token(token):
            otp_login(request, device)
            return redirect('admin:index')
            
        messages.error(request, "Invalid code.")
        return redirect('admin_mfa_verify')
