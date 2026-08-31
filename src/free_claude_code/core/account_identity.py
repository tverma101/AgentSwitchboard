"""Privacy-preserving identifiers for locally tracked provider accounts."""

import hashlib


def account_fingerprint(provider_id: str, account_id: str) -> str:
    """Return a stable, non-reversible label for a provider account.

    FCC stores this fingerprint in its metadata-only usage ledger instead of a
    provider account id or email address. The provider namespace is included
    so the same upstream identifier cannot collide across providers.
    """

    provider = provider_id.strip().casefold()
    account = account_id.strip()
    if not provider or not account:
        raise ValueError("provider_id and account_id are required")
    digest = hashlib.sha256(f"{provider}\x00{account}".encode()).hexdigest()
    return f"acct_{digest[:12]}"
