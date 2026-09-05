"""Independent secret store (v4 04 §"資料模型" footnote).

The store deliberately lives outside the main ``services/`` tree so
that audit reviews can locate it quickly. The store API is exposed
via ``backend.api.settings``; the service implementation lives in
``backend.services.secret_service`` and is re-exported here.
"""

from ..services.secret_service import SecretService, SecretMetadata

__all__ = ["SecretService", "SecretMetadata"]
