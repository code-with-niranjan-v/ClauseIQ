from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "circular-ingestion"
    host: str = "0.0.0.0"
    port: int = 8000

    # Kafka. The topic and payload are produced by circular-scanner's OutboxPublisher.
    consumer_enabled: bool = True
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic: str = "regulatory.document.ingested"
    kafka_dead_letter_topic: str = "regulatory.document.ingested.dlq"
    kafka_group_id: str = "circular-ingestion"
    max_attempts: int = 3  # first attempt plus two retries, then dead-letter
    retry_backoff_seconds: float = 5.0

    # MinIO. Same credentials the scanner uses to upload the PDFs.
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False
    max_pdf_bytes: int = 50 * 1024 * 1024

    # PostgreSQL with pgvector.
    database_url: str = "postgresql://clauseiq:clauseiq@postgres:5432/clauseiq"

    # Neo4j. Leave NEO4J_URI empty to skip graph writes during local development.
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Chunking.
    chunk_max_chars: int = 1500

    # Obligation extraction. Without LLM_MODEL the worker uses the rule-based extractor.
    llm_model: str = ""
    llm_provider: str = "openai"
    llm_base_url: str = ""
    llm_api_key: str = ""

    # Embeddings. "hash" is a local, deterministic placeholder. "openai" calls the API.
    embedding_provider: str = "hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 384


settings = Settings()
