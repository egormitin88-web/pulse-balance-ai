import os
import tempfile

os.environ["FITNESS_DATA_DIR"] = tempfile.mkdtemp(prefix="pulse-balance-tests-")

from fastapi.testclient import TestClient

from app.main import app
import app.ai as ai_module
import app.main as main_module
import app.security as security_module


def login(client: TestClient, email: str, password: str) -> None:
    result = client.post("/api/auth/login", json={"email": email, "password": password})
    assert result.status_code == 200, result.text


def test_public_catalog_and_role_isolation():
    with TestClient(app) as guest:
        assert len(guest.get("/api/plans").json()) == 4
        assert guest.get("/api/schedule").json()
        assert guest.get("/api/membership").status_code == 401
        login(guest, "anna@demo.pulsebalance.ru", "Demo2026!")
        assert guest.get("/api/admin/users").status_code == 403
        assert guest.put("/api/admin/key", json={"api_key": "sk-" + "x" * 40}).status_code == 403


def test_memory_survives_new_login_and_other_client_cannot_read_conversation():
    with TestClient(app) as anna:
        login(anna, "anna@demo.pulsebalance.ru", "Demo2026!")
        saved = anna.put("/api/memory", json={"category": "schedule", "key": "preferred_time", "value": "вечер"})
        assert saved.status_code == 200
        fact_id = saved.json()["id"]
        conversation_id = anna.post("/api/conversations").json()["id"]
        assert anna.post("/api/auth/logout").status_code == 200
        login(anna, "anna@demo.pulsebalance.ru", "Demo2026!")
        assert any(f["id"] == fact_id and f["value"] == "вечер" for f in anna.get("/api/memory").json())
        assert anna.get(f"/api/conversations/{conversation_id}").status_code == 200
        with TestClient(app) as boris:
            login(boris, "boris@demo.pulsebalance.ru", "Demo2026!")
            assert boris.get(f"/api/conversations/{conversation_id}").status_code == 404
            assert boris.delete(f"/api/memory/{fact_id}").status_code == 404
        assert anna.delete(f"/api/memory/{fact_id}").status_code == 200
        assert all(f["id"] != fact_id for f in anna.get("/api/memory").json())


def test_booking_capacity_and_cancellation():
    with TestClient(app) as client:
        login(client, "anna@demo.pulsebalance.ru", "Demo2026!")
        yoga = next(c for c in client.get("/api/schedule").json() if c["service_code"] == "yoga" and c["free_places"] == c["capacity"])
        created = client.post("/api/bookings", json={"class_id": yoga["id"]})
        assert created.status_code == 201, created.text
        assert client.post("/api/bookings", json={"class_id": yoga["id"]}).status_code == 409
        assert client.delete(f"/api/bookings/{created.json()['id']}").status_code == 200
        assert any(b["id"] == created.json()["id"] and b["status"] == "CANCELLED" for b in client.get("/api/bookings").json())


def test_chat_uses_saved_memory_after_new_conversation(monkeypatch):
    class FakeResponse:
        def __init__(self, text):
            self.output_text = text
            self.output = []

    class FakeResponses:
        def __init__(self):
            self.chat_calls = []

        def create(self, **kwargs):
            if "text" in kwargs:
                return FakeResponse('{"facts":[{"operation":"UPSERT","category":"schedule","key":"preferred_time","value":"утро"}]}')
            self.chat_calls.append(kwargs)
            return FakeResponse("Учту ваши предпочтения.")

    fake = FakeResponses()
    monkeypatch.setattr(ai_module, "client_for_saved_key", lambda: type("Client", (), {"responses": fake})())
    monkeypatch.setattr(main_module, "read_openai_key", lambda: "sk-test-not-a-real-key")
    with TestClient(app) as client:
        login(client, "dina@demo.pulsebalance.ru", "Demo2026!")
        first = client.post("/api/chat", json={"message": "Теперь могу тренироваться только утром"})
        assert first.status_code == 200, first.text
        assert any(item["key"] == "preferred_time" for item in first.json()["remembered"])
        second = client.post("/api/chat", json={"message": "Что мне выбрать?"})
        assert second.status_code == 200
        assert "утро" in str(fake.chat_calls[-1]["instructions"])


def test_admin_key_never_echoes_value(monkeypatch):
    captured = []
    monkeypatch.setattr(main_module, "save_openai_key", lambda value: captured.append(value) or "memory")
    with TestClient(app) as client:
        login(client, "admin@demo.pulsebalance.ru", "Admin2026!")
        secret = "sk-" + "x" * 40
        response = client.put("/api/admin/key", json={"api_key": secret})
        assert response.status_code == 200, response.text
        assert captured == [secret]
        assert secret not in response.text
        assert response.json()["storage"] == "memory"


def test_admin_key_uses_memory_when_windows_vault_is_unavailable(monkeypatch):
    def unavailable(*_args):
        raise OSError(1312, "Credential Manager unavailable")

    monkeypatch.setattr(security_module, "_memory_openai_key", None)
    monkeypatch.setattr(security_module.keyring, "set_password", unavailable)
    monkeypatch.setattr(security_module.keyring, "get_password", unavailable)
    monkeypatch.setattr(security_module.keyring, "delete_password", unavailable)
    secret = "sk-" + "x" * 40
    with TestClient(app) as client:
        login(client, "admin@demo.pulsebalance.ru", "Admin2026!")
        saved = client.put("/api/admin/key", json={"api_key": secret})
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"configured": True, "storage": "memory"}
        assert client.get("/api/admin/key").json() == {"configured": True, "storage": "memory"}
        assert client.delete("/api/admin/key").json() == {"configured": False, "storage": None}
        assert client.get("/api/admin/key").json() == {"configured": False, "storage": None}


def test_ai_errors_distinguish_network_from_exhausted_quota():
    import httpx
    from openai import APIConnectionError, RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    network = APIConnectionError(request=request)
    assert main_module.ai_error_detail(network)[0] == 503
    assert "подключиться" in main_module.ai_error_detail(network)[1]
    response = httpx.Response(429, request=request)
    quota = RateLimitError("quota exhausted", response=response, body={"code": "insufficient_quota"})
    assert "баланс" in main_module.ai_error_detail(quota)[1]


def test_failed_ai_request_does_not_duplicate_user_message(monkeypatch):
    import httpx
    from openai import APIConnectionError
    from sqlalchemy import func, select
    from app.db import SessionLocal
    from app.models import Conversation, Message, User

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    monkeypatch.setattr(main_module, "read_openai_key", lambda: "sk-diagnostic-not-a-real-key")

    def fail(*_args):
        raise APIConnectionError(request=request)

    monkeypatch.setattr(main_module, "chat_answer", fail)
    with TestClient(app) as client, SessionLocal() as db:
        login(client, "dina@demo.pulsebalance.ru", "Demo2026!")
        user = db.scalar(select(User).where(User.email == "dina@demo.pulsebalance.ru"))
        before = db.scalar(select(func.count(Message.id)).join(Conversation).where(Conversation.user_id == user.id))
        response = client.post("/api/chat", json={"message": "Тестовый вопрос"})
        assert response.status_code == 503
        assert "подключиться" in response.json()["detail"]
        db.expire_all()
        after = db.scalar(select(func.count(Message.id)).join(Conversation).where(Conversation.user_id == user.id))
        assert after == before


def test_agent_tool_call_reads_current_sql_catalog(monkeypatch):
    from app.db import SessionLocal
    from app.models import Conversation, Message, User
    from sqlalchemy import select

    class FakeCall:
        type = "function_call"
        name = "get_plans"
        arguments = "{}"
        call_id = "call_1"

        def model_dump(self, **_kwargs):
            return {"type": self.type, "name": self.name, "arguments": self.arguments, "call_id": self.call_id}

    class FakeResponses:
        def __init__(self):
            self.inputs = []

        def create(self, **kwargs):
            self.inputs.append(kwargs["input"])
            if len(self.inputs) == 1:
                return type("Response", (), {"output": [FakeCall()], "output_text": ""})()
            return type("Response", (), {"output": [], "output_text": "В каталоге четыре тарифа."})()

    fake = FakeResponses()
    monkeypatch.setattr(ai_module, "client_for_saved_key", lambda: type("Client", (), {"responses": fake})())
    with TestClient(app), SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "anna@demo.pulsebalance.ru"))
        conversation = Conversation(user_id=user.id, title="Тарифы")
        db.add(conversation); db.flush()
        message = Message(conversation_id=conversation.id, role="user", content="Какие тарифы есть?")
        db.add(message); db.commit()
        answer, actions = ai_module.chat_answer(db, user, conversation, [message])
        assert "четыре" in answer
        assert actions == []
        tool_outputs = [item for item in fake.inputs[1] if isinstance(item, dict) and item.get("type") == "function_call_output"]
        assert tool_outputs and "Старт" in tool_outputs[0]["output"]


def test_server_key_is_not_exposed_or_changed_by_demo_admin(monkeypatch):
    secret = "sk-" + "environment-test-placeholder" * 2
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    with TestClient(app) as client:
        login(client, "admin@demo.pulsebalance.ru", "Admin2026!")
        status = client.get("/api/admin/key")
        assert status.json() == {"configured": True, "storage": "environment"}
        assert secret not in status.text
        assert client.put("/api/admin/key", json={"api_key": "sk-" + "x" * 40}).status_code == 422
        assert client.delete("/api/admin/key").status_code == 409
        assert security_module.read_openai_key() == secret
