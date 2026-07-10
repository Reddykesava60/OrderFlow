import csv
import io
import logging
import secrets
import string
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Count, Q, Exists, OuterRef
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from owner.views.staff import _write_owner_audit
from core.mixins import OwnerRequiredMixin
from core.models import (
    AddOn, ItemType, MenuItem, MenuItemAddOn,
    OwnerAuditLog, PlatformFeeRecord, Restaurant, StaffFilter, User,
)
from core.ratelimit import rate_limit
from core.storage import get_supabase_storage_config, upload_bytes_public, upload_public_image
from core.timeutils import local_day_bounds
from kitchen.models import PaymentEvent
from ordering.models import Order, OrderItem, OrderItemAddOn
from ordering.orders.services import expire_overdue_unpaid_cash_orders

logger = logging.getLogger(__name__)


class ConfigView(OwnerRequiredMixin, View):

    def get(self, request):
        restaurant = self.get_restaurant()
        return render(request, 'owner/config.html', {'restaurant': restaurant, 'config': restaurant.config, 'menu_public_url': request.build_absolute_uri(reverse('ordering:menu', args=[restaurant.slug]))})

    def post(self, request):
        restaurant = self.get_restaurant()
        config = restaurant.config
        data = request.POST
        before_config = {'is_open': config.is_open, 'reopen_message': config.reopen_message, 'cash_enabled': config.cash_enabled, 'upi_enabled': config.upi_enabled, 'post_payment_enabled': config.post_payment_enabled, 'slug': restaurant.slug}
        config.is_open = 'is_open' in data
        config.reopen_message = data.get('reopen_message', '').strip()
        if config.admin_cash_enabled:
            config.cash_enabled = 'cash_enabled' in data
        if config.admin_upi_enabled:
            config.upi_enabled = 'upi_enabled' in data
        if config.admin_post_payment_enabled:
            config.post_payment_enabled = 'post_payment_enabled' in data

        if not config.cash_enabled and not config.upi_enabled and not config.post_payment_enabled:
            messages.error(request, 'At least one payment method must be enabled.')
            return redirect('owner:config')
        config.save()
        new_slug = data.get('slug', '').strip().lower()
        if new_slug and new_slug != restaurant.slug:
            from django.utils.text import slugify
            clean_slug = slugify(new_slug)
            if not clean_slug:
                messages.error(request, 'Invalid slug.')
                return redirect('owner:config')
            if Restaurant.objects.filter(slug=clean_slug).exclude(id=restaurant.id).exists():
                messages.error(request, f"Slug '{clean_slug}' is already taken.")
                return redirect('owner:config')
            restaurant.slug = clean_slug
            restaurant.menu_qr_code_url = ''
            restaurant.save(update_fields=['slug', 'menu_qr_code_url'])
            messages.info(request, f"Slug changed to '{clean_slug}'. Update your QR code.")
        messages.success(request, 'Settings saved.')
        _write_owner_audit(restaurant=restaurant, user=request.user, action=OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG, details={'restaurant_config_before': before_config, 'restaurant_config_after': {'is_open': config.is_open, 'reopen_message': config.reopen_message, 'cash_enabled': config.cash_enabled, 'upi_enabled': config.upi_enabled, 'post_payment_enabled': config.post_payment_enabled, 'slug': restaurant.slug}})
        return redirect('owner:config')

class MenuQrCodeDownloadView(OwnerRequiredMixin, View):
    """
    GET /owner/config/qr-code/menu.png
    Generates a branded QR code with the restaurant name above and
    "Scan to order" below. Returns it as a download and optionally
    uploads to Supabase Storage.
    """

    def get(self, request):
        from PIL import Image, ImageDraw, ImageFont

        restaurant = self.get_restaurant()
        menu_path = reverse('ordering:menu', args=[restaurant.slug])
        menu_url = request.build_absolute_uri(menu_path)

        # ── Generate raw QR code ─────────────────────────────────────────
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=10)
        qr.add_data(menu_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
        qr_w, qr_h = qr_img.size

        # ── Prepare fonts ────────────────────────────────────────────────
        import os

        def _find_font(names, size):
            """Try system font directories for the first match, then Pillow default."""
            search_dirs = [
                '/usr/share/fonts/truetype/dejavu',
                '/usr/share/fonts/truetype/liberation',
                '/usr/share/fonts/truetype',
                '/usr/share/fonts',
                'C:\\Windows\\Fonts',
            ]
            for name in names:
                # Try bare name first (Pillow's own search)
                try:
                    return ImageFont.truetype(name, size)
                except (OSError, IOError):
                    pass
                # Try with full paths
                for d in search_dirs:
                    path = os.path.join(d, name)
                    if os.path.isfile(path):
                        try:
                            return ImageFont.truetype(path, size)
                        except (OSError, IOError):
                            pass
            return ImageFont.load_default(size=size)

        title_font   = _find_font(['arialbd.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf'], 42)
        subtitle_font = _find_font(['arial.ttf', 'DejaVuSans.ttf', 'LiberationSans-Regular.ttf'], 28)
        caption_font  = _find_font(['arial.ttf', 'DejaVuSans.ttf', 'LiberationSans-Regular.ttf'], 18)
        footer_font   = _find_font(['arialbd.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf'], 14)

        # ── Measure text ─────────────────────────────────────────────────
        title_text = restaurant.name
        subtitle_text = "Scan to Order"
        caption_text = "Point your phone camera at the code"
        footer_text = "POWERED BY ORDER-FLOW"

        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        title_bbox = dummy.textbbox((0, 0), title_text, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        title_h = title_bbox[3] - title_bbox[1]

        subtitle_bbox = dummy.textbbox((0, 0), subtitle_text, font=subtitle_font)
        subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_h = subtitle_bbox[3] - subtitle_bbox[1]

        caption_bbox = dummy.textbbox((0, 0), caption_text, font=caption_font)
        caption_w = caption_bbox[2] - caption_bbox[0]
        caption_h = caption_bbox[3] - caption_bbox[1]

        footer_bbox = dummy.textbbox((0, 0), footer_text, font=footer_font)
        footer_w = footer_bbox[2] - footer_bbox[0]
        footer_h = footer_bbox[3] - footer_bbox[1]

        # ── Compose final image ──────────────────────────────────────────
        padding = 48
        gap = 24
        line_gap = 16          # space around the separator line
        caption_gap = 10       # space between subtitle and caption
        footer_gap = 32
        
        canvas_w = max(qr_w, title_w, subtitle_w, caption_w, footer_w) + padding * 2
        canvas_h = (padding + title_h + gap
                    + qr_h
                    + line_gap + 1 + line_gap   # separator line (1px)
                    + subtitle_h + caption_gap + caption_h
                    + footer_gap + footer_h
                    + padding)

        canvas = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(canvas)

        # Restaurant name (centred above QR)
        title_x = (canvas_w - title_w) // 2
        title_y = padding
        draw.text((title_x, title_y), title_text, fill='#005aa3', font=title_font)

        # QR code (centred)
        qr_x = (canvas_w - qr_w) // 2
        qr_y = padding + title_h + gap
        canvas.paste(qr_img, (qr_x, qr_y))

        # Thin separator line
        line_y = qr_y + qr_h + line_gap
        line_margin = padding + 40
        draw.line([(line_margin, line_y), (canvas_w - line_margin, line_y)], fill='#DDDDDD', width=1)

        # "Scan to Order" (centred below line)
        subtitle_x = (canvas_w - subtitle_w) // 2
        subtitle_y = line_y + line_gap
        draw.text((subtitle_x, subtitle_y), subtitle_text, fill='#222222', font=subtitle_font)

        # Helper caption (centred, lighter)
        caption_x = (canvas_w - caption_w) // 2
        caption_y = subtitle_y + subtitle_h + caption_gap
        draw.text((caption_x, caption_y), caption_text, fill='#999999', font=caption_font)

        # Footer (centred, bottom)
        footer_x = (canvas_w - footer_w) // 2
        footer_y = caption_y + caption_h + footer_gap
        draw.text((footer_x, footer_y), footer_text, fill='#AAAAAA', font=footer_font)

        # ── Save to bytes ────────────────────────────────────────────────
        buf = io.BytesIO()
        canvas.save(buf, format='PNG')
        png_bytes = buf.getvalue()

        if get_supabase_storage_config():
            try:
                public_url = upload_bytes_public(bucket='qr-codes', path=f'{restaurant.id}.png', content=png_bytes, content_type='image/png')
                restaurant.menu_qr_code_url = public_url
                restaurant.save(update_fields=['menu_qr_code_url'])
            except Exception:
                logger.exception('Failed uploading menu QR code to Supabase Storage for %s', restaurant.id)

        response = HttpResponse(png_bytes, content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="{restaurant.slug}_menu_qr.png"'
        return response