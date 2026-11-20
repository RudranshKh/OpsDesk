import os
import secrets
import json
import ipaddress
import re


def parse_trusted_proxy_ips(raw_value: str) -> list[str]:
    """Parse explicit trusted proxy IP/CIDR values; never accept a wildcard."""
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    if any(value == "*" for value in values):
        raise ValueError("TRUSTED_PROXY_IPS must contain explicit IP addresses or CIDR ranges")
    try:
        networks = [ipaddress.ip_network(value, strict=False) for value in values]
        if any(network.prefixlen == 0 for network in networks):
            raise ValueError
        return [str(network) for network in networks]
    except ValueError as error:
        raise ValueError(
            "TRUSTED_PROXY_IPS must contain valid IP addresses or CIDR ranges"
        ) from error


class Settings:
    """Environment-backed application settings."""

    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    app_name: str = os.getenv("APP_NAME", "OpsDesk API")
    api_prefix: str = os.getenv("API_PREFIX", "/api")
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite:///./opsdesk.db"
    )
    cors_origins: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    trusted_proxy_ips: list[str] = parse_trusted_proxy_ips(
        os.getenv("TRUSTED_PROXY_IPS", "")
    )
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    _configured_jwt_secret = os.getenv("JWT_SECRET_KEY")
    jwt_secret_configured: bool = bool(_configured_jwt_secret)
    jwt_secret_key: str = _configured_jwt_secret or secrets.token_urlsafe(48)
    jwt_issuer: str = os.getenv("JWT_ISSUER", "opsdesk")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "opsdesk-api")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
    demo_login_enabled: bool = os.getenv("DEMO_LOGIN_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    sla_targets = json.loads(os.getenv("SLA_TARGETS_JSON", """{
        "low": {"response_minutes": 1440, "resolution_minutes": 7200},
        "normal": {"response_minutes": 480, "resolution_minutes": 2880},
        "high": {"response_minutes": 120, "resolution_minutes": 720},
        "urgent": {"response_minutes": 30, "resolution_minutes": 120}
    }"""))
    sla_approaching_minutes: int = int(os.getenv("SLA_APPROACHING_MINUTES", "60"))
    sla_travel_urgent_minutes: int = int(os.getenv("SLA_TRAVEL_URGENT_MINUTES", "180"))
    sla_escalation_enabled: bool = os.getenv("SLA_ESCALATION_ENABLED", "true").lower() in {"1", "true", "yes"}
    sla_poll_seconds: int = max(10, int(os.getenv("SLA_POLL_SECONDS", "60")))

    def validate_startup(self) -> None:
        if self.app_env not in {"production", "prod"}:
            return
        if not self.jwt_secret_configured or not self._is_valid_production_jwt_secret(
            self.jwt_secret_key
        ):
            raise RuntimeError(
                "Production requires JWT_SECRET_KEY in generated format: exactly 64 lowercase hexadecimal characters."
            )

    @staticmethod
    def _is_valid_production_jwt_secret(value: str) -> bool:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            return False
        if value in {
            "0" * 64,
            "1" * 64,
            "deadbeef" * 8,
            "0123456789abcdef" * 4,
            "abcdef0123456789" * 4,
        }:
            return False
        for pattern_length in range(1, len(value) // 2 + 1):
            if len(value) % pattern_length == 0:
                pattern = value[:pattern_length]
                if pattern * (len(value) // pattern_length) == value:
                    return False
        return True


settings = Settings()
