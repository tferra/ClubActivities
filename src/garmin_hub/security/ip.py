"""Dirección de red del cliente tratada como dato personal (research R11)."""

import ipaddress

from starlette.requests import HTTPConnection

from garmin_hub.keys import DerivedKeys, hmac_digest

UNKNOWN = "unknown"


def client_ip(request: HTTPConnection) -> str:
    client = request.client
    return client.host if client and client.host else UNKNOWN


def ip_prefix(ip: str) -> str:
    """Reduce la dirección a su red: IPv4 /24, IPv6 /48."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return UNKNOWN
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def ip_hmac(keys: DerivedKeys, ip: str) -> bytes:
    return hmac_digest(keys.ip_rl, ip)
