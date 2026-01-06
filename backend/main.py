"""FastAPI backend for LLM Council."""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any
import uuid
import json
import asyncio

from . import storage
from .council import run_full_council, run_quick_council, run_light_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, stage3_synthesize_quick, calculate_aggregate_rankings
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)

# Configure rate limiting
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="LLM Council API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail="Rate limit exceeded"))

# Add trusted host middleware to prevent host header attacks
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "0.0.0.0"]
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str = Field(..., min_length=1, max_length=10000)
    quick_mode: bool = False  # Skip Stage 2 (peer ranking) for faster responses
    light_mode: bool = False  # Use lighter/cheaper models for simple queries
    
    @field_validator('content')
    @classmethod
    def content_not_empty(cls, v):
        """Ensure content is not just whitespace."""
        if not v.strip():
            raise ValueError('Message content cannot be empty or whitespace only')
        return v.strip()


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
@limiter.limit("10/minute")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    Rate limited to 10 requests per minute.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process with conversation history
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        conversation["messages"]  # Pass existing messages as history
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        stage1_results = []
        stage2_results = []
        stage3_result = {}
        user_message_added = False
        
        try:
            # Capture existing messages for history BEFORE adding new user message
            conversation_history = conversation["messages"].copy()
            
            # Add user message
            try:
                storage.add_user_message(conversation_id, request.content)
                user_message_added = True
            except Exception as e:
                logger.error(f"Failed to add user message: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': f'Failed to save message: {str(e)}'})}\n\n"
                return

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Light mode: use cheaper/faster models for simple queries
            if request.light_mode:
                try:
                    yield f"data: {json.dumps({'type': 'light_mode_start'})}\n\n"
                    stage1_results, stage2_results, stage3_result, metadata = await run_light_council(
                        request.content, conversation_history
                    )
                    yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"
                    yield f"data: {json.dumps({'type': 'stage2_skipped', 'light_mode': True})}\n\n"
                    yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result, 'metadata': metadata})}\n\n"
                except Exception as e:
                    logger.error(f"Light mode council failed: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Light mode failed: {str(e)}'})}\n\n"
                    return
            else:
                # Stage 1: Collect responses
                try:
                    yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
                    stage1_results = await stage1_collect_responses(request.content, conversation_history)
                    yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"
                    
                    if not stage1_results:
                        logger.error("Stage 1 produced no results")
                        yield f"data: {json.dumps({'type': 'error', 'message': 'No models responded. Please try again.'})}\n\n"
                        return
                except Exception as e:
                    logger.error(f"Stage 1 failed: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Stage 1 failed: {str(e)}'})}\n\n"
                    return

            # Quick mode: skip Stage 2 and use simplified Stage 3
            if not request.light_mode and request.quick_mode:
                yield f"data: {json.dumps({'type': 'stage2_skipped', 'quick_mode': True})}\n\n"
                
                # Stage 3 Quick: Synthesize without rankings
                try:
                    yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                    stage3_result = await stage3_synthesize_quick(request.content, stage1_results, conversation_history)
                    yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
                except Exception as e:
                    logger.error(f"Stage 3 quick synthesis failed: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Synthesis failed: {str(e)}'})}\n\n"
                    return
                
                stage2_results = []  # Empty for storage
            elif not request.light_mode:
                # Stage 2: Collect rankings
                try:
                    yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
                    stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results, conversation_history)
                    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
                    yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"
                except Exception as e:
                    logger.error(f"Stage 2 failed: {e}")
                    # Stage 2 failure: Continue to Stage 3 with empty rankings (degraded mode)
                    yield f"data: {json.dumps({'type': 'stage2_failed', 'message': f'Peer ranking failed: {str(e)}'})}\n\n"
                    stage2_results = []

                # Stage 3: Synthesize final answer
                try:
                    yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
                    if stage2_results:
                        stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results, conversation_history)
                    else:
                        # Fallback to quick synthesis if Stage 2 failed
                        stage3_result = await stage3_synthesize_quick(request.content, stage1_results, conversation_history)
                    yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
                except Exception as e:
                    logger.error(f"Stage 3 synthesis failed: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': f'Final synthesis failed: {str(e)}'})}\n\n"
                    return

            # Wait for title generation if it was started
            if title_task:
                try:
                    title = await asyncio.wait_for(title_task, timeout=10.0)
                    storage.update_conversation_title(conversation_id, title)
                    yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"
                except asyncio.TimeoutError:
                    logger.warning(f"Title generation timed out for conversation {conversation_id}")
                except Exception as e:
                    logger.warning(f"Title generation failed: {e}")

            # Save complete assistant message
            try:
                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    stage2_results,
                    stage3_result
                )
            except Exception as e:
                logger.error(f"Failed to save assistant message: {e}")
                # Message was already partially sent to user, so log error but don't fail
                yield f"data: {json.dumps({'type': 'warning', 'message': 'Failed to save response to conversation history'})}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            logger.error(f"Unexpected error in event_generator: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

