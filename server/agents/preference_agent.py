import json


class PreferenceAgent:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def run(self, user_message: str) -> dict:
        prompt = f"""你是用户偏好分析 Agent。
请从用户输入中提取长期出行偏好，只返回合法 JSON。

规则：
- “还”“也”“另外”表示 append，追加到已有偏好
- “改成”“换成”“搬家到”表示 replace，覆盖原偏好
- 首次提及某类偏好时使用 replace
- 没有偏好时返回空列表

输出格式：
{{"preferences":[{{"type":"偏好类型","value":"偏好值","action":"append或replace"}}],"has_preferences":true或false}}

用户输入：{user_message}"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "只输出合法JSON，不要输出其他内容。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            timeout=30,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)
