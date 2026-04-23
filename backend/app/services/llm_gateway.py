from openai import AsyncOpenAI


class LLMConnectionError(Exception):
    pass


class LLMGateway:
    """Async wrapper over one user's configured OpenAI-compatible endpoints.

    Chat and embedding endpoints are kept as separate clients so the user can
    point them at different servers (e.g. local vLLM for chat + OpenAI for
    embeddings).
    """

    def __init__(
        self,
        chat_base_url: str,
        chat_api_key: str,
        chat_model: str,
        embed_base_url: str,
        embed_api_key: str,
        embed_model: str,
        embed_dim: int,
    ):
        self._chat = AsyncOpenAI(base_url=chat_base_url, api_key=chat_api_key)
        self._embed = AsyncOpenAI(base_url=embed_base_url, api_key=embed_api_key)
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._embed_dim = embed_dim

    async def ping_chat(self) -> bool:
        try:
            await self._chat.chat.completions.create(
                model=self._chat_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as e:
            raise LLMConnectionError(f"chat ping failed: {e}") from e
        return True

    async def ping_embed(self) -> bool:
        try:
            r = await self._embed.embeddings.create(
                model=self._embed_model, input=["ping"]
            )
        except Exception as e:
            raise LLMConnectionError(f"embed ping failed: {e}") from e
        got = len(r.data[0].embedding)
        if got != self._embed_dim:
            raise LLMConnectionError(
                f"embed dim mismatch: config says {self._embed_dim}, "
                f"endpoint returned {got}"
            )
        return True

    async def chat(self, messages: list[dict], stream: bool = False):
        try:
            return await self._chat.chat.completions.create(
                model=self._chat_model, messages=messages, stream=stream,
            )
        except Exception as e:
            raise LLMConnectionError(f"chat failed: {e}") from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = await self._embed.embeddings.create(
                model=self._embed_model, input=texts
            )
        except Exception as e:
            raise LLMConnectionError(f"embed failed: {e}") from e
        return [d.embedding for d in r.data]
