"""
LLM factory — creates the right chat model based on LLM_PROVIDER env var.

Supported providers:
  bedrock   — AWS Bedrock (incl. Enterprise AI Gateway proxy)
  anthropic — Direct Anthropic API
  openai    — OpenAI API

Set in .env:
  LLM_PROVIDER=bedrock
  BEDROCK_BASE_URL=https://ai-gateway.example.com/bedrock
  BEDROCK_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
  AWS_REGION=us-east-1
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()


def build_llm(max_tokens: int = 150, temperature: float = 0.3):
    """Build the conversation LLM based on configured provider."""

    if LLM_PROVIDER == "bedrock":
        return _build_bedrock(max_tokens, temperature)
    elif LLM_PROVIDER == "openai":
        return _build_openai(max_tokens, temperature)
    else:
        return _build_anthropic(max_tokens, temperature)


def build_review_llm(max_tokens: int = 2000):
    """Build a more capable LLM for the review agent."""
    return build_llm(max_tokens=max_tokens, temperature=0.1)


def _build_bedrock(max_tokens: int, temperature: float):
    """
    AWS Bedrock — also supports AZ AI Gateway (bearer token auth).

    Enterprise Gateway uses Bearer token auth, not AWS Sig4.
    We use httpx directly to call the gateway, wrapped in a LangChain-compatible class.
    """
    base_url = os.environ.get("BEDROCK_BASE_URL", "")
    model = os.environ.get("BEDROCK_MODEL", "anthropic.claude-haiku-20240307-v1:0")
    token = os.environ.get("ANTHROPIC_API_KEY", "")
    auth_type = os.environ.get("BEDROCK_AUTH_TYPE", "aws")  # "bearer" for Enterprise gateway

    if base_url and auth_type == "bearer":
        # Enterprise Gateway: Bedrock InvokeModel endpoint with Bearer token auth.
        # Endpoint: {base_url}/model/{model_id}/invoke
        # Request/response: Anthropic Messages format (anthropic_version field)
        try:
            from langchain_core.language_models.chat_models import BaseChatModel
            from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
            from langchain_core.outputs import ChatGeneration, ChatResult
            from pydantic import Field
            import httpx, json as _json

            invoke_url = f"{base_url.rstrip('/')}/model/{model}/invoke"
            logger.info(f"LLM: Enterprise Gateway (bearer) {model} via {base_url}")

            class _AZGatewayChatModel(BaseChatModel):
                """Direct httpx wrapper for Enterprise Gateway Bedrock InvokeModel."""
                url: str = Field(...)
                bearer_token: str = Field(...)
                max_tok: int = Field(default=150)
                temp: float = Field(default=0.3)

                @property
                def _llm_type(self) -> str:
                    return "az_gateway_bedrock"

                def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                    import asyncio
                    return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))

                async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                    az_msgs, system_text = [], None
                    for m in messages:
                        if isinstance(m, SystemMessage):
                            system_text = m.content
                        elif isinstance(m, HumanMessage):
                            az_msgs.append({"role": "user", "content": m.content})
                        elif isinstance(m, AIMessage):
                            az_msgs.append({"role": "assistant", "content": m.content})
                    if not az_msgs:
                        az_msgs = [{"role": "user", "content": "Hello"}]
                    payload: dict = {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": self.max_tok,
                        "temperature": self.temp,
                        "messages": az_msgs,
                    }
                    if system_text:
                        payload["system"] = system_text
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post(
                            self.url,
                            headers={
                                "Authorization": f"Bearer {self.bearer_token}",
                                "Content-Type": "application/json",
                            },
                            content=_json.dumps(payload),
                        )
                        resp.raise_for_status()
                    data = resp.json()
                    text = data["content"][0]["text"] if data.get("content") else ""
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

                def bind_tools(self, tools, **kwargs):
                    """Ignore tools — Enterprise Gateway doesn't support tool calling."""
                    return self

            return _AZGatewayChatModel(
                url=invoke_url, bearer_token=token,
                max_tok=max_tokens, temp=temperature,
            )
        except Exception as e:
            logger.warning(f"Enterprise Gateway setup failed ({e}), falling back to Anthropic")
            return _build_anthropic(max_tokens, temperature)

    # Standard AWS Bedrock with Sig4 auth
    try:
        import boto3
        from langchain_aws import ChatBedrock
        region = os.environ.get("AWS_REGION", "us-east-1")
        kwargs: dict = {
            "model_id": model,
            "region_name": region,
            "model_kwargs": {"max_tokens": max_tokens, "temperature": temperature},
        }
        if base_url:
            session = boto3.Session(
                aws_access_key_id=token or "dummy",
                aws_secret_access_key=token or "dummy",
                region_name=region,
            )
            kwargs["client"] = session.client("bedrock-runtime", endpoint_url=base_url, region_name=region)
        logger.info(f"LLM: Bedrock {model}")
        return ChatBedrock(**kwargs)
    except ImportError:
        logger.warning("langchain-aws not installed, falling back to Anthropic")
        return _build_anthropic(max_tokens, temperature)


def _build_anthropic(max_tokens: int, temperature: float):
    """Direct Anthropic API."""
    from langchain_anthropic import ChatAnthropic

    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    # Strip Bedrock model ID format if present
    if model.startswith("us.") or model.startswith("eu."):
        model = "claude-haiku-4-5-20251001"

    logger.info(f"LLM: Anthropic {model}")
    return ChatAnthropic(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    )


def _build_openai(max_tokens: int, temperature: float):
    """OpenAI API."""
    from langchain_openai import ChatOpenAI

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    logger.info(f"LLM: OpenAI {model}")
    return ChatOpenAI(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
