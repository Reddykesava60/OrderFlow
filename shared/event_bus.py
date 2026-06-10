import logging
from typing import Callable, Type, Dict, List
from .events import DomainEvent

logger = logging.getLogger(__name__)

class EventBus:
    """
    In-memory event bus for synchronous decoupling of domain modules.
    Handlers should not execute long-running tasks synchronously.
    """
    def __init__(self):
        self._handlers: Dict[Type[DomainEvent], List[Callable[[DomainEvent], None]]] = {}

    def subscribe(self, event_type: Type[DomainEvent], handler: Callable[[DomainEvent], None]):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent):
        from django.db import transaction
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            def _execute_handler(h=handler, e=event):
                try:
                    h(e)
                except Exception as exc:
                    logger.exception("Error handling event %s with handler %s: %s", event_type, h, exc)
            
            # Ensure side-effects only run if the current DB transaction commits successfully.
            # If called outside a transaction block, this executes immediately.
            transaction.on_commit(_execute_handler)

# Global singleton event bus
event_bus = EventBus()
