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

    # OpenAI. The key is required for extraction, gap analysis and embeddings.
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_base_url: str = ""  # only for an OpenAI-compatible gateway
    # "llm" uses OpenAI. "rules" is an offline keyword extractor for development only.
    extraction_mode: str = "llm"

    # Embeddings. "openai" calls the API. "hash" is an offline placeholder for tests.
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Internal knowledge: policy handbook, control register and role directory.
    knowledge_dir: str = "sample-data"
    seed_knowledge_on_start: bool = True
    policy_top_k: int = 4
    control_top_k: int = 3

    # Policy Q&A. Sources below the cosine-similarity threshold are not shown to the model.
    chat_top_k: int = 5
    chat_min_similarity: float = 0.3

    # System assessments. Obligations below the similarity threshold to every system fact are not compared.
    system_min_similarity: float = 0.3
    system_max_obligations: int = 20

settings = Settings()
