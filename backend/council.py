"""3-stage LLM Council orchestration."""

from typing import List, Dict, Any, Tuple, Optional
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, COUNCIL_MODELS_LIGHT, CHAIRMAN_MODEL_LIGHT

# Maximum number of previous exchanges to include in context
MAX_HISTORY_EXCHANGES = 5

# Threshold for triggering summarization (number of exchanges)
SUMMARIZATION_THRESHOLD = 8

# Number of recent exchanges to keep verbatim (not summarized)
RECENT_EXCHANGES_TO_KEEP = 3


async def summarize_conversation(messages: List[Dict[str, Any]]) -> str:
    """
    Generate a concise summary of conversation messages.
    
    Args:
        messages: List of conversation messages to summarize
        
    Returns:
        A concise summary string
    """
    if not messages:
        return ""
    
    # Format messages for summarization
    conversation_text = []
    for msg in messages:
        if msg.get("role") == "user":
            conversation_text.append(f"User: {msg.get('content', '')}")
        elif msg.get("role") == "assistant":
            stage3 = msg.get("stage3", {})
            response = stage3.get("response", "")
            if response:
                # Truncate for summarization input
                if len(response) > 500:
                    response = response[:500] + "..."
                conversation_text.append(f"Council: {response}")
    
    if not conversation_text:
        return ""
    
    summary_prompt = f"""Summarize the following conversation in 2-3 concise sentences. 
Focus on the main topics discussed and any important conclusions or decisions.

Conversation:
{chr(10).join(conversation_text)}

Summary:"""

    messages_for_api = [{"role": "user", "content": summary_prompt}]
    
    # Use a fast model for summarization
    response = await query_model("google/gemini-2.5-flash", messages_for_api, timeout=30.0)
    
    if response is None:
        # Fallback: create a simple topic list
        return "Previous discussion covered multiple topics."
    
    return response.get('content', '').strip()


def format_conversation_history(messages: List[Dict[str, Any]], max_exchanges: int = MAX_HISTORY_EXCHANGES) -> str:
    """
    Format conversation history for inclusion in prompts (sync version).
    
    Args:
        messages: List of conversation messages (user and assistant)
        max_exchanges: Maximum number of exchanges to include
        
    Returns:
        Formatted history string
    """
    if not messages:
        return ""
    
    # Get last N exchanges (each exchange = user + assistant)
    # Take last max_exchanges * 2 messages (pairs)
    recent_messages = messages[-(max_exchanges * 2):]
    
    if not recent_messages:
        return ""
    
    history_parts = []
    for msg in recent_messages:
        if msg.get("role") == "user":
            history_parts.append(f"User: {msg.get('content', '')}")
        elif msg.get("role") == "assistant":
            # Extract the final synthesized response from Stage 3
            stage3 = msg.get("stage3", {})
            response = stage3.get("response", "")
            if response:
                # Truncate long responses to save tokens
                if len(response) > 1000:
                    response = response[:1000] + "..."
                history_parts.append(f"Council: {response}")
    
    if not history_parts:
        return ""
    
    return "[Previous conversation]\n" + "\n\n".join(history_parts) + "\n\n[Current question]\n"


async def format_conversation_history_with_summary(
    messages: List[Dict[str, Any]],
    max_exchanges: int = MAX_HISTORY_EXCHANGES
) -> str:
    """
    Format conversation history with auto-summarization for long conversations.
    
    For conversations exceeding SUMMARIZATION_THRESHOLD exchanges:
    - Summarizes older messages into a brief context
    - Keeps recent exchanges verbatim
    
    Args:
        messages: List of conversation messages (user and assistant)
        max_exchanges: Maximum number of recent exchanges to include verbatim
        
    Returns:
        Formatted history string with optional summary prefix
    """
    if not messages:
        return ""
    
    # Count exchanges (each user+assistant pair = 1 exchange)
    num_exchanges = len(messages) // 2
    
    # If under threshold, use simple formatting
    if num_exchanges <= SUMMARIZATION_THRESHOLD:
        return format_conversation_history(messages, max_exchanges)
    
    # Split messages: older ones to summarize, recent ones to keep verbatim
    recent_count = RECENT_EXCHANGES_TO_KEEP * 2  # messages, not exchanges
    older_messages = messages[:-recent_count] if recent_count < len(messages) else []
    recent_messages = messages[-recent_count:]
    
    # Generate summary of older messages
    summary = ""
    if older_messages:
        summary = await summarize_conversation(older_messages)
    
    # Format recent messages
    history_parts = []
    for msg in recent_messages:
        if msg.get("role") == "user":
            history_parts.append(f"User: {msg.get('content', '')}")
        elif msg.get("role") == "assistant":
            stage3 = msg.get("stage3", {})
            response = stage3.get("response", "")
            if response:
                if len(response) > 1000:
                    response = response[:1000] + "..."
                history_parts.append(f"Council: {response}")
    
    # Build final context
    context_parts = ["[Previous conversation]"]
    if summary:
        context_parts.append(f"[Summary of earlier discussion]\n{summary}")
    if history_parts:
        context_parts.append("[Recent exchanges]\n" + "\n\n".join(history_parts))
    context_parts.append("[Current question]")
    
    return "\n\n".join(context_parts) + "\n"


async def stage1_collect_responses(
    user_query: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    # Format the query with history context (with auto-summarization for long convos)
    history_context = await format_conversation_history_with_summary(conversation_history or [])
    full_query = history_context + user_query if history_context else user_query
    
    messages = [{"role": "user", "content": full_query}]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results with token usage
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "usage": response.get('usage', {})
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1
        conversation_history: Optional list of previous messages for context

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Format history context for ranking prompt
    history_context = format_conversation_history(conversation_history or [])
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    # Build context-aware ranking prompt
    context_section = ""
    if history_context:
        context_section = f"""Context from previous conversation:
{history_context}

"""
    
    ranking_prompt = f"""{context_section}You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed,
                "usage": response.get('usage', {})
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2
        conversation_history: Optional list of previous messages for context

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Format history context for chairman
    history_context = format_conversation_history(conversation_history or [])
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    # Build context-aware chairman prompt
    context_section = ""
    if history_context:
        context_section = f"""Previous Conversation Context:
{history_context}

"""
    
    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

{context_section}Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis.",
            "usage": {}
        }

    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', ''),
        "usage": response.get('usage', {})
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_council(
    user_query: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(user_query, conversation_history)

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(
        user_query, stage1_results, conversation_history
    )

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        conversation_history
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings
    }

    return stage1_results, stage2_results, stage3_result, metadata


async def run_quick_council(
    user_query: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List, List, Dict, Dict]:
    """
    Run a quick 2-stage council process (skips peer ranking).
    
    This mode is faster because it skips Stage 2 (peer ranking).
    The chairman synthesizes directly from Stage 1 responses.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context

    Returns:
        Tuple of (stage1_results, empty_stage2, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(user_query, conversation_history)

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Skip Stage 2 - chairman synthesizes directly from Stage 1
    # Build a modified Stage 3 prompt without ranking context
    stage3_result = await stage3_synthesize_quick(
        user_query,
        stage1_results,
        conversation_history
    )

    # Empty metadata since we skipped Stage 2
    metadata = {
        "quick_mode": True
    }

    return stage1_results, [], stage3_result, metadata


async def stage3_synthesize_quick(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Stage 3 Quick Mode: Chairman synthesizes without peer rankings.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        conversation_history: Optional list of previous messages for context

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Format history context for chairman
    history_context = format_conversation_history(conversation_history or [])
    
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    # Build context-aware chairman prompt (without peer rankings)
    context_section = ""
    if history_context:
        context_section = f"""Previous Conversation Context:
{history_context}

"""
    
    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question.

{context_section}Original Question: {user_query}

Model Responses:
{stage1_text}

Your task as Chairman is to synthesize all of these responses into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their unique insights
- Areas of agreement across models
- Any contradictions or different perspectives

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis.",
            "usage": {}
        }

    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', ''),
        "usage": response.get('usage', {})
    }


async def run_light_council(
    user_query: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List, List, Dict, Dict]:
    """
    Run a lightweight council with fewer/cheaper models.
    
    Uses COUNCIL_MODELS_LIGHT (3 fast models) instead of full council (5 flagship models).
    Skips Stage 2 (peer ranking) for faster responses.
    Uses CHAIRMAN_MODEL_LIGHT for synthesis.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context

    Returns:
        Tuple of (stage1_results, empty_stage2, stage3_result, metadata)
    """
    # Stage 1: Collect responses from light council
    history_context = await format_conversation_history_with_summary(conversation_history or [])
    full_query = history_context + user_query if history_context else user_query
    
    messages = [{"role": "user", "content": full_query}]
    responses = await query_models_parallel(COUNCIL_MODELS_LIGHT, messages)

    stage1_results = []
    for model, response in responses.items():
        if response is not None:
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "usage": response.get('usage', {})
            })

    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again.",
            "usage": {}
        }, {}

    # Skip Stage 2 - synthesize directly with light chairman
    stage3_result = await stage3_synthesize_light(
        user_query,
        stage1_results,
        conversation_history
    )

    metadata = {
        "light_mode": True,
        "models_used": COUNCIL_MODELS_LIGHT,
        "chairman": CHAIRMAN_MODEL_LIGHT
    }

    return stage1_results, [], stage3_result, metadata


async def stage3_synthesize_light(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Light Mode Stage 3: Fast chairman synthesizes responses.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        conversation_history: Optional list of previous messages for context

    Returns:
        Dict with 'model' and 'response' keys
    """
    history_context = format_conversation_history(conversation_history or [])
    
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    context_section = ""
    if history_context:
        context_section = f"""Previous Conversation Context:
{history_context}

"""
    
    chairman_prompt = f"""You are synthesizing responses from multiple AI models into a single clear answer.

{context_section}Question: {user_query}

Model Responses:
{stage1_text}

Provide a concise, accurate answer combining the best insights from all responses:"""

    messages = [{"role": "user", "content": chairman_prompt}]
    response = await query_model(CHAIRMAN_MODEL_LIGHT, messages)

    if response is None:
        return {
            "model": CHAIRMAN_MODEL_LIGHT,
            "response": "Error: Unable to generate synthesis.",
            "usage": {}
        }

    return {
        "model": CHAIRMAN_MODEL_LIGHT,
        "response": response.get('content', ''),
        "usage": response.get('usage', {})
    }
