from test_saas_isolation import factory, client, headers
from test_saas_customer_shopping import stocked
from app.services.ai_tools import tool_catalog

ACCEPT = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-11-25",
}


def rpc(client, method, params=None, auth=None):
    return client.post(
        "/api/v1/mcp",
        headers={**(auth or headers()), **ACCEPT},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_mcp_initialization_and_registry_discovery(client, factory):
    result = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert result.status_code == 200
    assert result.json()["result"]["protocolVersion"] == "2025-11-25"
    listed = rpc(client, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in listed] == [t["name"] for t in tool_catalog()]
    assert all(t["annotations"]["readOnlyHint"] for t in listed)


def test_mcp_calls_share_backend_tenant_scope_and_cannot_override_it(
    client, factory, stocked
):
    result = rpc(client, "tools/call", {"name": "get_catalog_overview"}).json()[
        "result"
    ]
    assert result["isError"] is False
    assert result["structuredContent"]["result"]["productos_activos"] == 1
    response = rpc(
        client, "tools/call", {"name": "get_catalog_overview"}, headers(2, 2, "b")
    )
    assert response.status_code == 200, response.text
    other = response.json()["result"]
    assert other["structuredContent"]["result"]["productos_con_stock"] == 0
    invalid = rpc(
        client,
        "tools/call",
        {"name": "get_catalog_overview", "arguments": {"tenant_id": 1}},
        headers(2, 2, "b"),
    ).json()
    assert invalid["error"]["code"] == -32602
    assert (
        rpc(
            client, "tools/call", {"name": "delete_product", "arguments": {"id": 1}}
        ).json()["error"]["code"]
        == -32602
    )
    uid, _, _ = stocked
    customer_tools = rpc(client, "tools/list", auth=headers(uid)).json()["result"][
        "tools"
    ]
    assert "get_business_indicators" not in {t["name"] for t in customer_tools}
    assert (
        rpc(
            client, "tools/call", {"name": "get_business_indicators"}, headers(uid)
        ).json()["error"]["code"]
        == -32602
    )
    indicators = rpc(
        client,
        "tools/call",
        {"name": "get_business_indicators", "arguments": {"days": 7}},
    ).json()["result"]
    assert indicators["isError"] is False


def test_mcp_auth_transport_origin_and_notifications(client, factory):
    assert client.post("/api/v1/mcp", headers=ACCEPT, json={}).status_code == 401
    assert (
        client.post(
            "/api/v1/mcp",
            headers={**headers(), **ACCEPT, "Origin": "https://untrusted.example"},
            json={},
        ).status_code
        == 403
    )
    assert client.post("/api/v1/mcp", headers=headers(), json={}).status_code == 406
    assert client.get("/api/v1/mcp", headers=headers()).status_code == 405
    r = client.post(
        "/api/v1/mcp",
        headers={**headers(), **ACCEPT},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert r.status_code == 202 and not r.content
    assert rpc(client, "unknown").json()["error"]["code"] == -32601
