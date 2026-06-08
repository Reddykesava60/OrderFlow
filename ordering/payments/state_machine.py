from django.db.models import F

from ordering.models import PAYMENT_STATE_TRANSITIONS, PaymentState


class PaymentStateMachine:
    transitions = PAYMENT_STATE_TRANSITIONS

    def can_transition(self, current, target):
        return current == target or target in self.transitions.get(current, set())

    def transition_locked(self, payment, target):
        if not self.can_transition(payment.state, target):
            raise ValueError(f"Invalid payment transition {payment.state} -> {target}")
        if payment.state != target:
            payment.state = target
            payment.version = F("version") + 1
        return payment
