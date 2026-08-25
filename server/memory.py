"""Two-layer memory with Redis cache and JSON fallback."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonMemory:
    def __init__(self, user_id: str):
        safe_user_id = user_id.replace("/", "_").replace("\\", "_")
        self.user_id = safe_user_id
        self.path = ROOT / "data" / "memory" / f"{safe_user_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.redis = self._connect_redis()

    def _connect_redis(self):
        if os.getenv("REDIS_ENABLED", "true").lower() != "true":
            return None
        try:
            from redis import Redis
            client = Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
            )
            client.ping()
            return client
        except Exception:
            return None

    def _load(self) -> dict:
        if not self.path.exists():
            return {"preferences": [], "sessions": {}, "long_term_summary": ""}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data.setdefault("preferences", [])
        data.setdefault("sessions", {})
        data.setdefault("long_term_summary", "")
        return data

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _redis_key(self, suffix: str) -> str:
        return f"travel:memory:{self.user_id}:{suffix}"

    def _redis_get_json(self, key: str):
        if not self.redis:
            return None
        try:
            raw = self.redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _redis_set_json(self, key: str, value, ttl: int | None = None) -> None:
        if not self.redis:
            return
        try:
            raw = json.dumps(value, ensure_ascii=False)
            self.redis.setex(key, ttl, raw) if ttl else self.redis.set(key, raw)
        except Exception:
            pass

    def get_preferences(self) -> dict:
        cached = self._redis_get_json(self._redis_key("preferences"))
        if isinstance(cached, dict):
            return cached
        data = self._load()
        preferences = {item["type"]: item["value"] for item in data.get("preferences", [])}
        self._redis_set_json(self._redis_key("preferences"), preferences)
        return preferences

    def apply_preferences(self, preferences: list[dict]) -> dict:
        data = self._load()
        items = data.setdefault("preferences", [])
        for item in preferences:
            pref_type = item.get("type")
            value = item.get("value")
            if not pref_type or value is None:
                continue
            existing = next((x for x in items if x.get("type") == pref_type), None)
            if item.get("action") == "append" and existing:
                values = existing["value"] if isinstance(existing["value"], list) else [existing["value"]]
                if value not in values:
                    values.append(value)
                existing["value"] = values
            elif existing:
                existing["value"] = value
            else:
                items.append({"type": pref_type, "value": value})
        self._save(data)
        current = {item["type"]: item["value"] for item in items}
        self._redis_set_json(self._redis_key("preferences"), current)
        return current

    def add_message(self, session_id: str, role: str, content: str, max_turns: int = 10) -> list[dict]:
        """保存短期记忆，只保留最近若干轮对话。"""
        data = self._load()
        messages = data.setdefault("sessions", {}).setdefault(session_id, [])
        messages.append({"role": role, "content": content, "created_at": _now()})
        messages = messages[-max_turns * 2:]
        data["sessions"][session_id] = messages
        self._save(data)
        self._redis_set_json(self._redis_key(f"short:{session_id}"), messages, ttl=3600)
        return messages

    def get_recent_messages(self, session_id: str, max_messages: int = 20) -> list[dict]:
        cached = self._redis_get_json(self._redis_key(f"short:{session_id}"))
        if isinstance(cached, list):
            return cached[-max_messages:]
        messages = self._load().get("sessions", {}).get(session_id, [])[-max_messages:]
        self._redis_set_json(self._redis_key(f"short:{session_id}"), messages, ttl=3600)
        return messages

    def get_summary(self) -> str:
        cached = self._redis_get_json(self._redis_key("summary"))
        if isinstance(cached, str):
            return cached
        summary = self._load().get("long_term_summary", "")
        if summary:
            self._redis_set_json(self._redis_key("summary"), summary)
        return summary

    def save_summary(self, summary: str) -> None:
        data = self._load()
        data["long_term_summary"] = summary
        data["summary_updated_at"] = _now()
        self._save(data)
        self._redis_set_json(self._redis_key("summary"), summary)

    def status(self, session_id: str) -> dict:
        return {
            "short_term_messages": len(self.get_recent_messages(session_id)),
            "long_term_preferences": self.get_preferences(),
            "long_term_summary": self.get_summary(),
            "redis_connected": bool(self.redis),
        }
