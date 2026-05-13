from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./expenses.db"
    debug: bool = True
    app_name: str = "Expenses"

    class Config:
        env_file = ".env"


settings = Settings()
