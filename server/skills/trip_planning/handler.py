from server.memory import JsonMemory


def run(message: str, user_id: str, client=None):
    from server.agentscope_workflow import run_trip_workflow
    return run_trip_workflow(message, JsonMemory(user_id).get_preferences())
