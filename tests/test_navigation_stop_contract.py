from types import SimpleNamespace as NS


def test_dedicated_estop_endpoint_interrupts_pending_task_before_release(fake_node, web_client):
    calls = []
    fake_node.navigation_tasks = NS(interrupt=lambda message: calls.append(message))
    assert web_client.post("/api/emergency-stop", json={"enabled": True}).status_code == 200
    assert len(calls) == 1 and fake_node.store.snapshot()["emergency_stop"]
    assert web_client.post("/api/emergency-stop", json={"enabled": False}).status_code == 200
    assert len(calls) == 1
