import sys

sys.path.insert(0, "src")

from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig


def main() -> None:
    client = OllamaClient(OllamaConfig(model="qwen2.5:7b-instruct-q4_0"))

    # 1) plain JSON mode (no schema)
    obj = client.chat_json(
        [{"role": "user", "content": 'Return JSON only: {"ok": true, "n": 1}'}],
        json_schema=None,  # forces format="json"
    )
    print("json:", obj)

    # 2) minimal schema mode (small, safe)
    schema = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "n": {"type": "integer"},
        },
        "required": ["ok", "n"],
        "additionalProperties": False,
    }
    obj2 = client.chat_json(
        [{"role": "user", "content": "Return JSON with ok=true and n=2"}],
        json_schema=schema,
    )
    print("schema:", obj2)


if __name__ == "__main__":
    main()
