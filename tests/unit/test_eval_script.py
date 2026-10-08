from pathlib import Path

import yaml

from src.scripts.eval_agent_routing import SCENARIOS, check, cost

BODY = {
    "response": "Prueba con riego por goteo y revisa la humedad.",
    "metadata": {
        "tool_calls": [
            {"name": "load_skill", "args": {"skill_name": "ficha-tomate"}, "ok": True},
            {"name": "get_forecast", "args": {}, "ok": True},
        ],
        "usage": {"llm_calls": 2, "prompt_tokens": 30_000, "cached_tokens": 20_000, "output_tokens": 500,
                  "thinking_tokens": 100},
    },
}


def test_cost_uses_the_cached_rate_for_cached_tokens_and_bills_thinking_as_output():
    usage = BODY["metadata"]["usage"]
    expected = (10_000 * 0.30 + 20_000 * 0.03 + 600 * 2.50) / 1_000_000
    assert abs(cost(usage) - expected) < 1e-9


def test_check_reports_each_kind_of_miss():
    assert check({"skills_any": ["ficha-tomate"], "tools_any": ["get_forecast"], "max_llm_calls": 3}, BODY) == []
    problems = check(
        {"skills_any": ["plagas-tomate"], "tools_any": ["web_search"], "forbid_tools": ["get_forecast"],
         "max_llm_calls": 1, "forbid_text_regex": "riego"},
        BODY,
    )
    assert len(problems) == 5


def test_scenario_file_is_well_formed_and_names_real_skills_and_tools():
    from src.agent.prompts.knowledge_skills import skill_catalog
    from src.agent.preflight.engine import READ_ONLY_TOOLS

    scenarios = yaml.safe_load(Path(SCENARIOS).read_text())
    assert len(scenarios) >= 10 and len({s["id"] for s in scenarios}) == len(scenarios)
    assert {"AR", "MX"} <= {s["country"] for s in scenarios}
    skills = set(skill_catalog())
    for s in scenarios:
        assert s["message"] and s["country"] in ("AR", "MX"), s["id"]
        assert set(s.get("skills_any", [])) <= skills, s["id"]
        assert set(s.get("tools_any", [])) <= READ_ONLY_TOOLS | {"log_event"}, s["id"]
