import httpx
import pytest

from eivon.adapters.models import CompatibleModel, ModelUnavailable
from eivon.adapters.network import OutboundDenied, check_destination
from eivon.core.contracts import ModelMessage, ModelSpec


async def test_stream_assembles_fragmented_tool_arguments_and_usage():
    body = "\n".join(
        [
            'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"lookup","arguments":"{\\"x\\":"}}]}}]}',
            'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"42}"}}]},"finish_reason":"tool_calls"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}',
            "data: [DONE]",
            "",
        ]
    )

    async def handler(request):
        assert request.headers["authorization"] == "Bearer token"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = []

    async def emit(kind, data):
        events.append((kind, data))

    model = CompatibleModel(
        ModelSpec(model="test", base_url="https://model.test/v1"),
        "token",
        ("model.test",),
        httpx.MockTransport(handler),
    )
    result = await model.complete([ModelMessage(role="user", content="hi")], [], emit)
    assert result.tool_calls[0].arguments == {"x": 42}
    assert result.usage["total_tokens"] == 20


async def test_incomplete_model_stream_fails():
    model = CompatibleModel(
        ModelSpec(model="test", base_url="https://model.test"),
        None,
        ("model.test",),
        httpx.MockTransport(lambda request: httpx.Response(200, text='data: {"choices":[]}\n')),
    )

    async def emit(*args):
        pass

    with pytest.raises(ModelUnavailable, match="disconnected"):
        await model.complete([], [], emit)


def test_outbound_destinations_are_explicit():
    with pytest.raises(OutboundDenied):
        check_destination("http://localhost/private", ("api.example.com",))
    with pytest.raises(OutboundDenied):
        check_destination("https://user:password@api.example.com", ("api.example.com",))
    with pytest.raises(OutboundDenied):
        check_destination("https://api.example.com:8443/", ("api.example.com",))
    assert check_destination("http://localhost:11434/v1", ("localhost:11434",))
