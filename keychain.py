"""macOS Keychain utilities for loading secrets."""

import subprocess
import os
from typing import Optional


def get_keychain_secret(name: str) -> Optional[str]:
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
        # Only strip trailing newline, preserve any intentional whitespace in password
        return result.stdout.rstrip('\n')
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
        ("YNAB_API_TOKEN", "YNAB_API_TOKEN"),
    ]

    for env_var, keychain_key in credentials:
        # Always prefer Keychain value (overwrite any existing env var)
        value = get_keychain_secret(keychain_key)
        if value:
            os.environ[env_var] = value
