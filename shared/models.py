import uuid
from django.db import models
from django.utils import timezone

def generate_uuid():
    """
    Generate a UUID.
    Currently falls back to uuid4. In a real Python 3.14+ environment or with
    a third-party package, this would return uuid.uuid7() for time-sortable PKs.
    """
    return uuid.uuid4()

class DomainModel(models.Model):
    """
    Abstract base model for all greenfield domain models.
    Enforces UUID primary keys and standard audit timestamps.
    """
    id = models.UUIDField(primary_key=True, default=generate_uuid, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
