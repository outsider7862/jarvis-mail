"""
Shared rate limiter.

Lives here rather than in main.py because the route modules need to import
`limiter` to decorate endpoints, and main.py imports those route modules —
defining it in main.py would be a circular import.

Keyed on remote address: these limits are a blunt abuse/runaway guard for
unauthenticated or expensive endpoints, not per-user quotas.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
