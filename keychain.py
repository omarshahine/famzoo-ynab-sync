"""macOS Keychain utilities for loading secrets."""

import subprocess
import os


def get_keychain_secret(name: str) -> str | None:
    """
    Get a secret from macOS Keychain.

    Args:
        name: The secret name (will be prefixed with "env/")

    Returns:
        The secret value, or None if not found
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", f"env/{name}", "-w"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def load_famzoo_credentials() -> None:
    """
    Load FamZoo and YNAB credentials from Keychain into environment variables.
    Keychain values take precedence over existing env vars.

    Secrets loaded:
        - FAMZOO_PASSWORD
        - YNAB_API_TOKEN (stored as env/FAMZOO_YNAB_API_TOKEN to distinguish from main YNAB token)
    """
    credentials = [
        ("FAMZOO_PASSWORD", "FAMZOO_PASSWORD"),
        ("YNAB_API_TOKEN", "FAMZOO_YNAB_API_TOKEN"),  # Different keychain key to avoid collision
    ]

    for env_var, keychain_key in credentials:
        # Always prefer Keychain value (overwrite any existing env var)
        value = get_keychain_secret(keychain_key)
        if value:
            os.environ[env_var] = value
