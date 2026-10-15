from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "negotiator"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_webhook_secret: str = ""
    elevenlabs_phone_number_id: str = ""  # Twilio number imported into ElevenLabs
    jwt_secret: str = "change-me"
    # Comma-separated browser origins allowed to call the API (your frontend).
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Optional regex for origins that change per deploy, e.g. Vercel previews:
    # ^https://negotiator-[a-z0-9-]+\.vercel\.app$
    cors_origin_regex: str = ""


settings = Settings()
