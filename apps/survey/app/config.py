from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./survey.db"

    # console | twilio | africastalking
    sms_provider: str = "console"

    # How bare local numbers (07...) are interpreted: KE or GB.
    default_country: str = "KE"

    # Expose POST /webhooks/simulate for local testing. Disable in production.
    enable_simulator: bool = True

    # Substituted into {utility} placeholders in survey texts (e.g. S0).
    utility_name: str = "[UTILITY]"

    # GridCook API (apps/api) used by `survey respondent import-gridcook`.
    gridcook_api_base: str = "https://delft-api.flonat.com"

    # Local timezone for the panel scheduler (send days, Sundays rule).
    timezone: str = "Africa/Nairobi"

    # Streak bonus: extra credit after N consecutive completed weekly/monthly surveys.
    streak_length: int = 4
    streak_bonus_kwh: float = 0.5

    # Twilio (UK testing)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_validate_signature: bool = False
    public_base_url: str = ""

    # Africa's Talking (Kenya production)
    at_username: str = "sandbox"
    at_api_key: str = ""
    at_sender_id: str = ""
    at_environment: str = "sandbox"


@lru_cache
def get_settings() -> Settings:
    return Settings()
