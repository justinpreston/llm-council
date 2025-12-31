"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.2",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-3-flash-preview",
    "x-ai/grok-4.1-fast",
    "deepseek/deepseek-v3.2",
]

# Light council - faster/cheaper models for simple queries
COUNCIL_MODELS_LIGHT = [
    "google/gemini-2.5-flash",
    "deepseek/deepseek-v3.2",
    "x-ai/grok-4.1-fast",
]

# Chairman model - synthesizes final response (Opus 4.5 for best synthesis)
CHAIRMAN_MODEL = "anthropic/claude-opus-4.5"

# Light chairman - faster model for simple queries
CHAIRMAN_MODEL_LIGHT = "google/gemini-2.5-flash"

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"
