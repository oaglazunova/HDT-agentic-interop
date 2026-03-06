from __future__ import annotations

import os
from typing import Any
import logging
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from hdt_config.settings import init_runtime

from .provider_executor import ProviderAgentExecutor

log = logging.getLogger(__name__)


def build_app(*, base_url: str) -> Any:
    card = AgentCard(
        name="HDT Provider Agent",
        description="Provider-side A2A agent that serves algorithm contract schemas and their hashes.",
        url=base_url,
        version="0.1.0",
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="contract_registry",
                name="Contract registry",
                description="List contracts or fetch a contract bundle (schema + expected hash).",
                tags=["contract", "schema", "hash"],
                examples=[
                    '{"op":"list_contracts"}',
                    '{"op":"get_contract","algo_id":"provider.obesityCoach","algo_version":"0.1.0"}',
                ],
            )
        ],
    )

    handler = DefaultRequestHandler(
        agent_executor=ProviderAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(agent_card=card, http_handler=handler)
    return server.build()


def main() -> None:
    init_runtime()
    log.info("Starting User/Provider A2A server …")

    host = os.getenv("HDT_PROVIDER_A2A_HOST", "127.0.0.1")
    port = int(os.getenv("HDT_PROVIDER_A2A_PORT", "9100"))
    advertise_host = os.getenv("HDT_PROVIDER_A2A_ADVERTISE_HOST", "localhost")
    base_url = os.getenv("HDT_PROVIDER_A2A_URL", f"http://{advertise_host}:{port}/")

    uvicorn.run(
        build_app(base_url=base_url), host=host, port=port, log_level=os.getenv("HDT_LOG_LEVEL", "info").lower()
    )


if __name__ == "__main__":
    main()
