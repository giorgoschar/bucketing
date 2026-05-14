from pydantic_settings import BaseSettings
from pydantic import model_validator


class Settings(BaseSettings):
    app_secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./expenses.db"
    debug: bool = True
    app_name: str = "Expenses"
    allow_registration: bool = False

    @model_validator(mode="after")
    def _guard_production_defaults(self) -> "Settings":
        if not self.debug and self.app_secret_key == "dev-secret-change-me":
            raise RuntimeError(
                "APP_SECRET_KEY must be changed from the default value before running in production. "
                "Set the APP_SECRET_KEY environment variable."
            )
        return self

    class Config:
        env_file = ".env"


settings = Settings()
