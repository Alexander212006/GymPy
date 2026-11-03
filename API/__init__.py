"""External service integrations used by GymPy."""

from .brevo import send_client_welcome_email

__all__ = ["send_client_welcome_email"]
