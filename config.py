"""Configuration management for FamZoo-YNAB sync."""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    famzoo_family_name: str
    famzoo_member_name: str
    famzoo_password: str
    famzoo_account_name: str  # Account to select from dropdown (e.g., "Kids Spending" or partial match)
    ynab_api_token: str
    ynab_budget_id: str
    ynab_account_id: str
    ynab_transfer_account_id: Optional[str] = None  # Account ID for transfers (e.g., Checking)

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "Config":
        """Load configuration from .env file and environment variables."""
        load_dotenv(env_path)

        required_vars = [
            "FAMZOO_FAMILY_NAME",
            "FAMZOO_MEMBER_NAME",
            "FAMZOO_PASSWORD",
            "FAMZOO_ACCOUNT_NAME",
            "YNAB_API_TOKEN",
            "YNAB_BUDGET_ID",
            "YNAB_ACCOUNT_ID",
        ]

        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        return cls(
            famzoo_family_name=os.getenv("FAMZOO_FAMILY_NAME"),
            famzoo_member_name=os.getenv("FAMZOO_MEMBER_NAME"),
            famzoo_password=os.getenv("FAMZOO_PASSWORD"),
            famzoo_account_name=os.getenv("FAMZOO_ACCOUNT_NAME"),
            ynab_api_token=os.getenv("YNAB_API_TOKEN"),
            ynab_budget_id=os.getenv("YNAB_BUDGET_ID"),
            ynab_account_id=os.getenv("YNAB_ACCOUNT_ID"),
            ynab_transfer_account_id=os.getenv("YNAB_TRANSFER_ACCOUNT_ID"),
        )
