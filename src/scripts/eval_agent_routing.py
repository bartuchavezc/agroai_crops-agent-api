"""
Evaluates how the real model routes questions — which skills and tools the agent gathers, how many model calls and
tokens a turn costs, and whether the voice matches the country — with and without the preflight.

It talks to the REAL Gemini API with your key and spends some quota (a few calls per scenario and mode). It is not part
of the test suite. The database it uses must be migrated (`alembic upgrade head`).

    GEMINI_API_KEY=... DATABASE_URL=postgresql+asyncpg://... \\
        uv run python -m src.scripts.eval_agent_routing [--mode both|preflight|plain] [--only ID] [--out FILE.json]

Scenarios: tests/evals/scenarios.yaml. Prices (per million tokens) are Gemini 3.5 Flash-Lite's list prices as published
at ai.google.dev/gemini-api/docs/pricing; change PRICES if you evaluate another model. Cached tokens are billed at the
cache rate whether the cache is implicit or explicit; thinking tokens count as output.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "tests" / "evals" / "scenarios.yaml"
PRICES = {"input": 0.30, "cached": 0.03, "output": 2.50}  # USD per 1M tokens
FIELDS = {
    "AR": {"name": "Huerta", "city": "La Plata", "latitude": -34.92, "longitude": -57.95},
    "MX": {"name": "Parcela", "city": "Irapuato", "latitude": 20.68, "longitude": -101.35},
}


def cost(usage: dict) -> float:
    uncached = max(usage["prompt_tokens"] - usage["cached_tokens"], 0)
    return (
        uncached * PRICES["input"] + usage["cached_tokens"] * PRICES["cached"]
        + (usage["output_tokens"] + usage["thinking_tokens"]) * PRICES["output"]
    ) / 1_000_000


def check(scenario: dict, body: dict) -> list[str]:
    """What this turn got wrong, as short strings (empty = passed)."""
    meta = body["metadata"]
    calls = meta["tool_calls"]
    skills = {c["args"].get("skill_name") for c in calls if c["name"] == "load_skill"}
    tools = {c["name"] for c in calls if c["name"] != "load_skill"}
    usage = meta.get("usage") or {}
    problems = []
    if scenario.get("skills_any") and not skills & set(scenario["skills_any"]):
        problems.append(f"skills: esperaba alguno de {scenario['skills_any']}, cargó {sorted(skills)}")
    if scenario.get("tools_any") and not tools & set(scenario["tools_any"]):
        problems.append(f"tools: esperaba alguna de {scenario['tools_any']}, usó {sorted(tools)}")
    if bad := tools & set(scenario.get("forbid_tools", [])):
        problems.append(f"tools prohibidas usadas: {sorted(bad)}")
    if scenario.get("max_llm_calls") and usage.get("llm_calls", 0) > scenario["max_llm_calls"]:
        problems.append(f"{usage['llm_calls']} llamadas al modelo (tope {scenario['max_llm_calls']})")
    text = body["response"]
    if scenario.get("forbid_text_regex") and re.search(scenario["forbid_text_regex"], text, re.IGNORECASE):
        problems.append("la respuesta usa una voz que no es la del país")
    if scenario.get("require_text_regex") and not re.search(scenario["require_text_regex"], text, re.IGNORECASE):
        problems.append("a la respuesta le falta lo requerido")
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m src.scripts.eval_agent_routing")
    parser.add_argument("--mode", choices=["both", "preflight", "plain"], default="both")
    parser.add_argument("--only", help="run a single scenario id")
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS)
    parser.add_argument("--out", type=Path, help="write the full results as JSON")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY (a real key: this evaluation calls the Gemini API).")
        return 2
    os.environ.update({"DEV_MODE": "true", "ALLOW_PUBLIC_SIGNUP": "true"})

    import httpx

    from src.main import create_app

    scenarios = [s for s in yaml.safe_load(args.scenarios.read_text()) if not args.only or s["id"] == args.only]
    app = create_app()
    runner = app.state.container.agent.runner()
    modes = ["preflight", "plain"] if args.mode == "both" else [args.mode]
    results = []

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval", timeout=180) as http:
        users = {}
        for country in sorted({s["country"] for s in scenarios}):
            email = f"eval-{country.lower()}-{uuid.uuid4().hex[:8]}@example.com"
            signed = await http.post(
                "/api/v1/auth/signup", json={"email": email, "password": "eval-pass-1234", "country": country}
            )
            signed.raise_for_status()
            headers = {"Authorization": f"Bearer {signed.json()['access_token']}"}
            (await http.put(
                "/api/v1/me/provider-credentials/gemini", headers=headers, json={"api_key": api_key}
            )).raise_for_status()
            created = await http.post("/api/v1/farm-management/fields", headers=headers, json=FIELDS[country])
            created.raise_for_status()
            users[country] = headers

        for scenario in scenarios:
            for mode in modes:
                runner.preflight.enabled = mode == "preflight"
                response = await http.post(
                    "/api/v1/chat", headers=users[scenario["country"]], json={"message": scenario["message"]}
                )
                if response.status_code != 200:
                    results.append({"id": scenario["id"], "mode": mode, "error": response.text[:200]})
                    print(f"{scenario['id']:<28} {mode:<9} ERROR {response.status_code}: {response.text[:100]}")
                    continue
                body = response.json()
                usage = body["metadata"].get("usage") or dict.fromkeys(
                    ("llm_calls", "prompt_tokens", "cached_tokens", "output_tokens", "thinking_tokens"), 0
                )
                problems = check(scenario, body)
                calls = body["metadata"]["tool_calls"]
                results.append({
                    "id": scenario["id"], "mode": mode, "passed": not problems, "problems": problems, "usage": usage,
                    "usd": round(cost(usage), 5),
                    "skills": [c["args"].get("skill_name") for c in calls if c["name"] == "load_skill"],
                    "tools": [c["name"] for c in calls if c["name"] != "load_skill"],
                    "response": body["response"],
                })
                flag = "OK  " if not problems else "FAIL"
                print(
                    f"{scenario['id']:<28} {mode:<9} {flag} calls={usage['llm_calls']} "
                    f"prompt={usage['prompt_tokens']:>7} cached={usage['cached_tokens']:>7} "
                    f"out={usage['output_tokens'] + usage['thinking_tokens']:>5} ${cost(usage):.4f}  "
                    f"skills={results[-1]['skills']} tools={results[-1]['tools']}"
                )
                for problem in problems:
                    print(f"{'':<39}- {problem}")

    print("\nTotales por modo")
    for mode in modes:
        rows = [r for r in results if r["mode"] == mode and "usage" in r]
        if not rows:
            continue
        print(
            f"  {mode:<9} pasaron {sum(r['passed'] for r in rows)}/{len(rows)}"
            f" · llamadas {sum(r['usage']['llm_calls'] for r in rows)}"
            f" · tokens de entrada {sum(r['usage']['prompt_tokens'] for r in rows):,}"
            f" · costo estimado ${sum(r['usd'] for r in rows):.4f}"
        )
    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\nResultados completos en {args.out}")
    return 0 if all(r.get("passed", False) for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
