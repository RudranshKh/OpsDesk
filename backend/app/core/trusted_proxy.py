import ipaddress
from collections.abc import Iterable


class TrustedProxyHeadersMiddleware:
    """Use X-Forwarded-For only when the direct peer is explicitly trusted."""

    def __init__(self, app, trusted_proxy_ips: Iterable[str]):
        self.app = app
        self.trusted_networks = tuple(
            ipaddress.ip_network(value, strict=False) for value in trusted_proxy_ips
        )

    def _is_trusted(self, value: str) -> bool:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        return any(address in network for network in self.trusted_networks)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            client = scope.get("client")
            if client is not None and self._is_trusted(client[0]):
                forwarded_values = [
                    value.decode("latin1")
                    for name, value in scope.get("headers", [])
                    if name.lower() == b"x-forwarded-for"
                ]
                forwarded_hosts = [
                    host.strip()
                    for value in forwarded_values
                    for host in value.split(",")
                ]
                if forwarded_hosts and all(self._is_ip(host) for host in forwarded_hosts):
                    forwarded_addresses = [ipaddress.ip_address(host) for host in forwarded_hosts]
                    client_address = next(
                        (
                            address
                            for address in reversed(forwarded_addresses)
                            if not self._is_trusted(str(address))
                        ),
                        forwarded_addresses[0],
                    )
                    scope["client"] = (str(client_address), client[1])
        await self.app(scope, receive, send)

    @staticmethod
    def _is_ip(value: str) -> bool:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return False
        return True
