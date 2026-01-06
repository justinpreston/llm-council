"""OpenRouter API client for making LLM requests."""

import httpx
import asyncio
import logging
import random
from typing import List, Dict, Any, Optional
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 30.0  # seconds
RETRY_MULTIPLIER = 2.0  # exponential backoff
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}  # Timeout, Rate limit, Server errors


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    max_retries: int = MAX_RETRIES
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API with exponential backoff retry logic.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    last_error = None
    delay = INITIAL_RETRY_DELAY

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    OPENROUTER_API_URL,
                    headers=headers,
                    json=payload
                )
                
                # Check for retryable errors
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < max_retries:
                        wait_time = min(
                            delay * (RETRY_MULTIPLIER ** attempt) + random.uniform(0, 1),
                            MAX_RETRY_DELAY
                        )
                        logger.warning(
                            f"Model {model} returned {response.status_code}, "
                            f"retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Model {model} failed after {max_retries} retries: {last_error}")
                        return None
                
                response.raise_for_status()

                data = response.json()
                message = data['choices'][0]['message']
                
                # Extract token usage if available
                usage = data.get('usage', {})

                logger.info(f"Model {model} responded successfully after {attempt} attempts")
                return {
                    'content': message.get('content'),
                    'reasoning_details': message.get('reasoning_details'),
                    'usage': {
                        'prompt_tokens': usage.get('prompt_tokens', 0),
                        'completion_tokens': usage.get('completion_tokens', 0),
                        'total_tokens': usage.get('total_tokens', 0)
                    },
                    'model': model
                }

        except asyncio.TimeoutError as e:
            last_error = f"Timeout after {timeout}s"
            if attempt < max_retries:
                wait_time = min(
                    delay * (RETRY_MULTIPLIER ** attempt) + random.uniform(0, 1),
                    MAX_RETRY_DELAY
                )
                logger.warning(
                    f"Model {model} timed out, "
                    f"retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Model {model} failed after {max_retries} retries: {last_error}")
                return None

        except httpx.HTTPError as e:
            last_error = str(e)
            if attempt < max_retries:
                wait_time = min(
                    delay * (RETRY_MULTIPLIER ** attempt) + random.uniform(0, 1),
                    MAX_RETRY_DELAY
                )
                logger.warning(
                    f"Model {model} HTTP error ({last_error}), "
                    f"retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Model {model} failed after {max_retries} retries: {last_error}")
                return None

        except Exception as e:
            last_error = str(e)
            logger.error(f"Unexpected error querying model {model}: {last_error}")
            return None

    logger.error(f"Model {model} exhausted all retries. Last error: {last_error}")
    return None



async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # Create tasks for all models
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
