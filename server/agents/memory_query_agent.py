import json

from server.memory import JsonMemory


class MemoryQueryAgent:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def run(self, user_id: str) -> dict:
        preferences = JsonMemory(user_id).get_preferences()
        preference_text = json.dumps(preferences, ensure_ascii=False)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是用户记忆查询 Agent，请基于提供的真实数据回答，不要编造。"},
                {"role": "user", "content": f"请整理用户已保存的出行偏好：{preference_text}"},
            ],
            stream=False,
            timeout=30,
        )
        return {"answer": response.choices[0].message.content, "preferences": preferences}
