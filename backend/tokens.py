"""Token counting utilities for managing context windows."""

import logging
from typing import List, Dict, Any, Optional

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

logger = logging.getLogger(__name__)

# Rough token estimates (characters / this number ≈ tokens)
TOKENS_PER_CHAR_ESTIMATE = 4


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count tokens in text using tiktoken if available, otherwise estimate.
    
    Args:
        text: The text to count tokens for
        model: The model to use for tokenization (if tiktoken available)
        
    Returns:
        Estimated or actual token count
    """
    if not TIKTOKEN_AVAILABLE:
        # Fallback: rough estimate (1 token ≈ 4 characters)
        return len(text) // TOKENS_PER_CHAR_ESTIMATE
    
    try:
        encoding = tiktoken.encoding_for_model(model)
        tokens = encoding.encode(text)
        return len(tokens)
    except Exception as e:
        logger.warning(f"Failed to count tokens for model {model}: {e}. Using estimate.")
        return len(text) // TOKENS_PER_CHAR_ESTIMATE


def count_messages_tokens(messages: List[Dict[str, str]], model: str = "gpt-4") -> int:
    """
    Count tokens in a message list (like those sent to APIs).
    
    Accounts for the overhead of the message format:
    - Each message adds ~4 tokens for role/content structure
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        model: The model to use for tokenization
        
    Returns:
        Total token count
    """
    total_tokens = 0
    
    for message in messages:
        # Count tokens in the content
        total_tokens += count_tokens(message.get('content', ''), model)
        # Add overhead for role and formatting
        total_tokens += 4
    
    # Add overhead for message array structure
    total_tokens += 5
    
    return total_tokens


def should_summarize_history(
    messages: List[Dict[str, Any]],
    max_tokens: int = 4000,
    model: str = "gpt-4"
) -> bool:
    """
    Check if conversation history should be summarized to stay within token budget.
    
    Args:
        messages: The conversation history
        max_tokens: Maximum tokens allowed for history
        model: Model to use for token counting
        
    Returns:
        True if history exceeds token budget
    """
    total_tokens = 0
    
    for msg in messages:
        if msg.get("role") == "user":
            total_tokens += count_tokens(msg.get("content", ""), model)
        elif msg.get("role") == "assistant":
            stage3 = msg.get("stage3", {})
            response = stage3.get("response", "")
            total_tokens += count_tokens(response, model)
        
        # Early exit if exceeded
        if total_tokens >= max_tokens:
            return True
    
    return total_tokens >= max_tokens


def estimate_api_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "gpt-4"
) -> Dict[str, float]:
    """
    Estimate API cost based on token usage.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: The model (for pricing lookup)
        
    Returns:
        Dict with 'input_cost', 'output_cost', 'total_cost' in USD
    """
    # Pricing per 1M tokens (as of early 2024 via OpenRouter)
    pricing = {
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        "gemini": {"input": 0.5, "output": 1.5},
        "grok": {"input": 5.0, "output": 15.0},
        "deepseek": {"input": 0.14, "output": 0.28},
    }
    
    # Get model pricing (default to claude-3-sonnet if unknown)
    model_pricing = pricing.get(model, pricing["claude-3-sonnet"])
    
    input_cost = (input_tokens / 1_000_000) * model_pricing["input"]
    output_cost = (output_tokens / 1_000_000) * model_pricing["output"]
    
    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6)
    }
