"""Test defaults so the suite runs from a bare checkout.

`app.config.settings` is built at import time and requires a secret and
database coordinates. Supply harmless placeholders unless the caller has
set real ones; no test opens a real database connection.
"""

import os

_DEFAULTS = {
    "APP_SECRET_KEY": "test-secret-key-for-ci-only-0123456789",
    "APP_ENV": "development",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "ops_dashboard",
    "POSTGRES_USER": "ops_user",
    "POSTGRES_PASSWORD": "test-password",
}

for _name, _value in _DEFAULTS.items():
    os.environ.setdefault(_name, _value)
