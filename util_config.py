"""
Project configuration loader for nsclient_test_base.

Non-sensitive settings (URLs, usernames, flags) live in data/config.json.
Sensitive values (API tokens, passwords) are stored encrypted via util_secrets
and injected into the returned ProjectConfig automatically.

To set up secrets:
    python tool/manage_secrets.py init
    python tool/manage_secrets.py set confluence_api_token
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "data" / "config.json"

SENSITIVE_FIELDS = {"api_token", "password"}


@dataclass
class ConfluenceConfig:
    base_url: str = "https://netskope.atlassian.net/wiki"
    username: str = ""
    api_token: str = ""


@dataclass
class ProjectConfig:
    tenant_hostname: str = ""
    is_64bit: bool = True
    log_dir: str = "log"
    confluence: ConfluenceConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.confluence is None:
            self.confluence = ConfluenceConfig()


def load_config(path: Path | None = None) -> ProjectConfig:
    """Load ProjectConfig from JSON file.  Missing file returns defaults."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        log.warning("Config file not found: %s — using defaults", config_path)
        return ProjectConfig()

    try:
        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        log.exception("Failed to read config: %s", config_path)
        return ProjectConfig()

    confluence_data = data.get("confluence", {})
    confluence = ConfluenceConfig(
        base_url=confluence_data.get("base_url", "https://netskope.atlassian.net/wiki"),
        username=confluence_data.get("username", ""),
        api_token=confluence_data.get("api_token", ""),
    )

    config = ProjectConfig(
        tenant_hostname=data.get("tenant_hostname", ""),
        is_64bit=data.get("is_64bit", True),
        log_dir=data.get("log_dir", "log"),
        confluence=confluence,
    )

    # Inject encrypted secrets — silently skipped if secrets store not set up
    _inject_secrets(config)
    return config


def _inject_secrets(config: "ProjectConfig") -> None:
    """Overwrite blank sensitive fields with values from the encrypted secrets store."""
    try:
        from util_secrets import get_secret, SECRET_CONFLUENCE_API_TOKEN
        token = get_secret(SECRET_CONFLUENCE_API_TOKEN)
        if token and not config.confluence.api_token:
            config.confluence.api_token = token
            log.debug("Injected confluence_api_token from secrets store")
    except Exception:
        # secrets store unavailable or key missing — silently continue
        pass


def save_config(config: ProjectConfig, path: Path | None = None) -> None:
    """Save ProjectConfig to JSON, stripping sensitive fields."""
    config_path = path or DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = asdict(config)
    _strip_sensitive(data)

    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4)
        log.info("Config saved: %s", config_path)
    except Exception:
        log.exception("Failed to save config: %s", config_path)


def _strip_sensitive(data: dict) -> None:
    """Recursively remove sensitive fields from a dict in-place."""
    for key in list(data.keys()):
        if key in SENSITIVE_FIELDS:
            data[key] = ""
        elif isinstance(data[key], dict):
            _strip_sensitive(data[key])
