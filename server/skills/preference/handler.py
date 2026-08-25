from server.memory import JsonMemory


def run(message: str, user_id: str, client=None):
    try:
        from server.agentscope_workflow import run_preference_workflow
        return run_preference_workflow(message, JsonMemory(user_id).get_preferences())
    except ImportError:
        from server.agents.preference_agent import PreferenceAgent
        return PreferenceAgent(client=client, model="deepseek-v4-flash").run(message)
