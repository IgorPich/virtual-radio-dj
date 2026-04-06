"""Mock Ollama API response payloads."""

GENERATE_SUCCESS = {
    "model": "mistral",
    "response": "Did you know that Freddie Mercury could sing across four octaves?",
    "done": True,
}

GENERATE_EMPTY = {
    "model": "mistral",
    "response": "",
    "done": True,
}

TAGS_RESPONSE = {
    "models": [
        {"name": "mistral:latest", "size": 5_000_000_000},
        {"name": "llama2:latest", "size": 4_000_000_000},
    ],
}
