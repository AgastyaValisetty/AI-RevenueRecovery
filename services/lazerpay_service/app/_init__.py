"""LazerPay Payment Gateway Service.

Main entry point for the LazerPay microservice.
Exposes REST API for payment processing, retries, and payment links.
"""

from .config import Settings
from .api import router

# Service metadata
VERSION = "1.0.0"
DESCRIPTION = "Payment gateway simulating Razorpay-like behavior for revenue recovery simulation"


def get_settings() -> Settings:
    """Get settings instance, preferring environment variables."""
    return Settings.from_env()