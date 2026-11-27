from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "circular-ingestion"
    host: str = "0.0.0.0"
    port: int = 8000

    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic: str = "regulatory.document.ingested"
    kafka_group_id: str = "circular-ingestion"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False


settings = Settings()
