import os


def ipv4_only() -> bool:
    """Read the startup policy without changing either HTTP client's state."""
    value = os.environ.get('BLREC_IPV4', '').strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('', '0', 'false', 'no', 'off'):
        return False
    raise ValueError('BLREC_IPV4 must be 1/true/yes/on or 0/false/no/off (or empty)')
