from django.contrib.auth.models import AbstractUser
from django.db import models
from shared.models import generate_uuid, DomainModel

class User(AbstractUser):
    """
    Greenfield User model.
    Inherits from AbstractUser for compatibility with Django's auth system,
    but replaces the PK with a UUID.
    """
    id = models.UUIDField(primary_key=True, default=generate_uuid, editable=False)

    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        STAFF = 'STAFF', 'Staff'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STAFF)
    
    # Soft reference to Tenant operations (Restaurant)
    restaurant_id = models.UUIDField(null=True, blank=True, help_text="Soft reference to operations.Restaurant")

    # Permissions
    allow_cash_collection = models.BooleanField(default=False)
    allow_view_all_orders = models.BooleanField(default=False)
    allow_order_completion = models.BooleanField(default=False)
    
    must_change_password = models.BooleanField(default=False)
    photo_url = models.TextField(blank=True)

    class Meta:
        db_table = 'identity_user'

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER
