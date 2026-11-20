"""The OpenAI-compatible client against a mocked Groq stream (no network)."""
import json

import httpx
import pytest

from laghu_voice.services.llm_openai import LLMError, LLMStats, OpenAICompatLLM


def sse(*objs):
    return "".join(f"data: {json.dumps(o, ensure_ascii=False)}\n\n" for o in objs) + "data: [DONE]\n\n"


def chunk(content=None, reasoning=None, finish=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning"] = reasoning
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


async def test_streams_content_skips_reasoning_and_sends_groq_params():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        body = sse(chunk(reasoning="सोच रहा हूँ"), chunk("जी, "), chunk("आपका लोन"), chunk(" मंज़ूर है।", finish="stop"),
                   {"choices": [], "x_groq": {"usage": {"prompt_tokens": 12, "completion_tokens": 7}}})
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    llm = OpenAICompatLLM("https://api.groq.com/openai/v1", "k", "openai/gpt-oss-20b",
                          transport=httpx.MockTransport(handler))
    stats = LLMStats()
    out = [t async for t in llm.stream([{"role": "user", "content": "नमस्ते"}], stats=stats)]
    await llm.aclose()
    assert "".join(out) == "जी, आपका लोन मंज़ूर है।"
    assert seen["body"]["reasoning_effort"] == "low" and seen["body"]["include_reasoning"] is False
    assert seen["body"]["stream"] is True and seen["auth"] == "Bearer k"
    assert stats.ttft_ms is not None and stats.total_ms >= stats.ttft_ms
    assert stats.usage["completion_tokens"] == 7 and stats.finish_reason == "stop"


async def test_non_reasoning_model_gets_no_reasoning_params():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=sse(chunk("ok")))

    llm = OpenAICompatLLM("http://x/v1", "", "llama-3.3-70b-versatile", transport=httpx.MockTransport(handler))
    assert [t async for t in llm.stream([])] == ["ok"]
    await llm.aclose()
    assert "reasoning_effort" not in seen["body"] and "include_reasoning" not in seen["body"]


async def test_http_error_raises_with_detail():
    llm = OpenAICompatLLM("http://x/v1", "", "m", transport=httpx.MockTransport(
        lambda r: httpx.Response(429, text='{"error": "rate limit"}')))
    with pytest.raises(LLMError, match="429.*rate limit"):
        [t async for t in llm.stream([])]
    await llm.aclose()
