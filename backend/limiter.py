import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# In test mode, key every request uniquely so rate limits never fire
def _key_func(request):
    if os.getenv("TESTING") == "1":
        import uuid
        return str(uuid.uuid4())
    return get_remote_address(request)

limiter = Limiter(key_func=_key_func)
