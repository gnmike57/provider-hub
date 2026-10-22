"""Minimal A2A server using NanoGPT as the model provider.

VERIFIED to import against a2a-sdk 1.2.2 (the version installed here).

IMPORTANT API NOTE: the published docs snippet uses `a2a.server.apps.A2AStarletteApplication`
and `a2a.utils.errors.ServerError`. Neither exists in 1.2.2, and the types are **protobuf**
(not pydantic). The working entry point is
`a2a.server.routes.fastapi_routes.add_a2a_routes_to_fastapi`, and the error base class is
`a2a.utils.errors.A2AError` / `InternalError`. Field names differ from the docs too
(e.g. `supported_interfaces`, not `url`/`preferred_transport`).

Run:  uvicorn a2a_server_starter:app --host 127.0.0.1 --port 8000
Env:  NANOGPT_API_KEY (required)
"""
import os

from openai import AsyncOpenAI

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    InternalError,
    Message,
    Part,
    TaskState,
    TaskStatus,
)
from fastapi import FastAPI

NANOGPT_BASE = "https://nano-gpt.com/api/v1"
MODEL_ALIAS = "claw-medium"  # stable alias for agent workloads

nanogpt = AsyncOpenAI(api_key=os.environ["NANOGPT_API_KEY"], base_url=NANOGPT_BASE)


async def generate_reply(prompt: str) -> str:
    """Model adapter kept separate from the protocol layer."""
    response = await nanogpt.chat.completions.create(
        model=MODEL_ALIAS,
        messages=[
            {"role": "system", "content": "You are a focused remote agent. Return a useful final answer."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""


def _text_of(message) -> str:
    out = ""
    for p in getattr(message, "parts", []) or []:
        txt = getattr(p, "text", None)
        if txt:
            out += txt
    return out


class NanoGPTAgentExecutor(AgentExecutor):
    """Your A2A layer owns the Agent Card, task lifecycle, and caller auth."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = _text_of(context.message) if context.message else ""
        try:
            answer = await generate_reply(text)
        except Exception as e:  # bounded error: never leak prompts/keys/provider detail
            status = TaskStatus(state=TaskState.TASK_STATE_FAILED,
                                message=Message(role=2, parts=[Part(text=f"error: {type(e).__name__}")]))
            await event_queue.enqueue_event(status)
            return
        status = TaskStatus(state=TaskState.TASK_STATE_COMPLETED,
                            message=Message(role=2, parts=[Part(text=answer)]))
        await event_queue.enqueue_event(status)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise InternalError(message="cancel not supported")


agent_card = AgentCard(
    name="NanoGPT A2A Agent",
    description="A2A agent backed by NanoGPT model inference.",
    version="1.0.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    skills=[AgentSkill(id="chat", name="chat", description="Answer a prompt",
                       tags=["chat"], examples=["hello"])],
    # A2A 1.0: declare supportedInterfaces per protocol binding + version.
    supported_interfaces=[
        AgentInterface(url="http://127.0.0.1:8000", protocol_binding="JSONRPC", protocol_version="1.0"),
    ],
    # Declare security_schemes/security_requirements for real deployments.
    # NEVER put the NanoGPT key in the card or send it to an A2A caller.
)

handler = DefaultRequestHandler(agent_executor=NanoGPTAgentExecutor(), task_store=InMemoryTaskStore(),
                                agent_card=agent_card)

app = FastAPI(title="NanoGPT A2A agent")
add_a2a_routes_to_fastapi(
    app,
    agent_card_routes=create_agent_card_routes(agent_card),
    jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    rest_routes=create_rest_routes(handler),
)


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": MODEL_ALIAS, "base": NANOGPT_BASE}