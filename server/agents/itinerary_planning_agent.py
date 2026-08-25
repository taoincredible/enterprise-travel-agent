import json


class ItineraryPlanningAgent:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def run(self, user_message: str, event: dict, preferences: dict) -> dict:
        prompt = f"""你是行程规划 Agent。
请根据用户需求、已提取的行程信息和用户偏好，生成实用的出差行程。

用户需求：{user_message}
行程信息：{json.dumps(event, ensure_ascii=False)}
用户偏好：{json.dumps(preferences, ensure_ascii=False)}

如果缺少关键信息，仍然给出可用的初步方案，并在 missing_info 中列出需要确认的内容。
不要编造实时车次、票价、天气或酒店空房。
只返回合法 JSON：
{{"itinerary":{{"title":"","duration":"","route":"","daily_plans":[],"notes":[],"estimated_budget":""}},"planning_complete":true,"missing_info":[]}}"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是专业的差旅行程规划专家，只输出合法JSON。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            timeout=30,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)
