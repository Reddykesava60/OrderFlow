from django.contrib.auth.hashers import PBKDF2PasswordHasher

class CustomerPINHasher(PBKDF2PasswordHasher):
    """
    PBKDF2 hasher for customer PINs.

    PINs are low entropy, so new hashes must not use a very low work factor.
    Existing hashes keep verifying with the iteration count encoded in the hash.
    """
    algorithm = "customer_pin"
    iterations = 20000
