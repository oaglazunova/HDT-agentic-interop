from __future__ import annotations

import os
from typing import Any

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from .user_executor import UserAgentExecutor


def build_app(*, base_url: str) -> Any:
    card = AgentCard(
        name="HDT User Agent",
        description="User-side A2A agent that synthesizes a MappingPlanCandidate by calling a provider agent and running a validate/repair loop.",
        url=base_url,
        version="0.1.0",
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="mapping_plan_synthesis",
                name="Mapping plan synthesis",
                description="Fetch provider contract schema+hash and synthesize a MappingPlanCandidate from a vault_catalog.",
                tags=["mapping", "schema", "plan", "repair"],
                examples=[
                    (
                        '{"op":"mapping_plan.synthesize","provider_url":"http://localhost:9100/","algo_id":"provider.riskScore","algo_version":"1.2.0",'
                        '"vault_catalog":{"datasets":[{"dataset_id":"vault_dataset_A","tables":[{"table_name":"transactions","columns":[{"name":"dob","type":"date"}]}]}]}}'
                    ),
                ],
            )
        ],
    )

    handler = DefaultRequestHandler(
        agent_executor=UserAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(agent_card=card, http_handler=handler)
    return server.build()


def main() -> None:
    host = os.getenv("HDT_USER_A2A_HOST", "127.0.0.1")
    port = int(os.getenv("HDT_USER_A2A_PORT", "9200"))
    advertise_host = os.getenv("HDT_USER_A2A_ADVERTISE_HOST", "localhost")
    base_url = os.getenv("HDT_USER_A2A_URL", f"http://{advertise_host}:{port}/")

    uvicorn.run(build_app(base_url=base_url), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
