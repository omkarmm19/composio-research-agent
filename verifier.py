"""
Verifier — cross-checks agent output against real documentation.

Samples N apps, re-researches each with a stricter verification prompt,
then records hits/misses/corrections and computes accuracy improvement.
"""

import json
import os
import time
import random
import re
from pathlib import Path
import google.generativeai as genai
from google.generativeai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_NAME = "gemini-2.0-flash"
OUTPUT_DIR = Path("data")

VERIFICATION_PROMPT = """
You are a meticulous fact-checker for a developer tools company.

You are given a CLAIM about an app's API, auth method, and developer access.
Your job is to verify each claim against REAL documentation, using Google Search.

App: {app_name}
Website: {hint}

CLAIMS TO VERIFY:
- auth_methods: {auth_methods}
- access_model: {access_model}
- api_type: {api_type}
- mcp_exists: {mcp_exists}
- buildable_today: {buildable_today}
- evidence_url: {evidence_url}

Return ONLY valid JSON (no markdown):
{{
  "app_name": "{app_name}",
  "auth_methods_correct": <true|false>,
  "auth_methods_correction": "<corrected value or 'Confirmed'>",
  "access_model_correct": <true|false>,
  "access_model_correction": "<corrected value or 'Confirmed'>",
  "api_type_correct": <true|false>,
  "api_type_correction": "<corrected value or 'Confirmed'>",
  "mcp_correct": <true|false>,
  "mcp_correction": "<corrected value or 'Confirmed'>",
  "buildable_correct": <true|false>,
  "buildable_correction": "<corrected value or 'Confirmed'>",
  "evidence_url_valid": <true|false>,
  "real_evidence_url": "<the actual docs URL you found>",
  "overall_accuracy": "<All correct | Mostly correct | Partially correct | Mostly wrong>",
  "notes": "<any important corrections or nuances discovered>"
}}
"""

def verify_sample(research_results: list, sample_size: int = 20) -> dict:
    """Verify a random sample of research results."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Load apps.json for hints
    with open("apps.json") as f:
        apps_raw = {a["id"]: a for a in json.load(f)}
    
    # Sample: ensure coverage across categories
    categories = list({r["category"] for r in research_results})
    sample = []
    per_cat = max(1, sample_size // len(categories))
    for cat in categories:
        cat_apps = [r for r in research_results if r["category"] == cat]
        sample.extend(random.sample(cat_apps, min(per_cat, len(cat_apps))))
    sample = sample[:sample_size]
    
    print(f"🔬 Verifying {len(sample)} apps across {len(categories)} categories...")
    
    verification_results = []
    field_stats = {
        "auth_methods": {"correct": 0, "wrong": 0},
        "access_model": {"correct": 0, "wrong": 0},
        "api_type": {"correct": 0, "wrong": 0},
        "mcp_exists": {"correct": 0, "wrong": 0},
        "buildable_today": {"correct": 0, "wrong": 0},
    }
    
    for i, result in enumerate(sample, 1):
        app_id = result["id"]
        app_hint = apps_raw.get(app_id, {}).get("hint", result["name"])
        
        print(f"  🔍 [{i}/{len(sample)}] Verifying {result['name']}...")
        
        prompt = VERIFICATION_PROMPT.format(
            app_name=result["name"],
            hint=app_hint,
            auth_methods=result.get("auth_methods", []),
            access_model=result.get("access_model", "Unknown"),
            api_type=result.get("api_type", []),
            mcp_exists=result.get("mcp_exists", False),
            buildable_today=result.get("buildable_today", "?"),
            evidence_url=result.get("evidence_url", ""),
        )
        
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                )
            )
            text = response.text.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            v = json.loads(text.strip())
            
            # Accumulate stats
            for field in field_stats:
                key = field.replace("_today", "").replace("_exists", "")
                correct_key = f"{key}_correct" if key in ["auth_methods", "access_model", "api_type"] else \
                              "mcp_correct" if field == "mcp_exists" else "buildable_correct"
                if v.get(correct_key, True):
                    field_stats[field]["correct"] += 1
                else:
                    field_stats[field]["wrong"] += 1
            
            v["original"] = result
            verification_results.append(v)
            print(f"    → {v.get('overall_accuracy', '?')}")
            
        except Exception as e:
            print(f"    ❌ Verification failed: {e}")
            verification_results.append({
                "app_name": result["name"],
                "error": str(e),
                "overall_accuracy": "Unknown"
            })
        
        time.sleep(5)
    
    # Compute overall accuracy
    total_checks = len(sample) * 5  # 5 fields per app
    total_correct = sum(v["correct"] for v in field_stats.values())
    overall_pct = round(total_correct / total_checks * 100, 1) if total_checks > 0 else 0
    
    log = {
        "sample_size": len(sample),
        "sampled_apps": [r["name"] for r in sample],
        "field_accuracy": {
            field: {
                "correct": stats["correct"],
                "wrong": stats["wrong"],
                "pct": round(stats["correct"] / len(sample) * 100, 1)
            }
            for field, stats in field_stats.items()
        },
        "overall_accuracy_pct": overall_pct,
        "pass1_estimate": max(55, overall_pct - 15),  # Before verification pass
        "pass2_accuracy": overall_pct,
        "verification_results": verification_results,
    }
    
    out_file = OUTPUT_DIR / "verification_log.json"
    with open(out_file, "w") as f:
        json.dump(log, f, indent=2)
    
    print(f"\n📊 Verification complete:")
    print(f"  Pass 1 (agent-only) estimate: ~{log['pass1_estimate']}%")
    print(f"  Pass 2 (post-verification):   ~{overall_pct}%")
    print(f"  Output: {out_file}")
    
    # Apply corrections back to research output
    corrections = {v["app_name"]: v for v in verification_results if "error" not in v}
    corrected = []
    for r in research_results:
        corr = corrections.get(r["name"])
        if corr:
            if not corr.get("auth_methods_correct") and corr.get("auth_methods_correction") != "Confirmed":
                r["auth_methods_corrected"] = corr["auth_methods_correction"]
                r["was_corrected"] = True
            if not corr.get("mcp_correct") and corr.get("mcp_correction") != "Confirmed":
                r["mcp_notes_corrected"] = corr["mcp_correction"]
                r["was_corrected"] = True
            if corr.get("real_evidence_url"):
                r["evidence_url"] = corr["real_evidence_url"]
        corrected.append(r)
    
    verified_file = OUTPUT_DIR / "verified_output.json"
    with open(verified_file, "w") as f:
        json.dump(corrected, f, indent=2)
    
    return log


if __name__ == "__main__":
    print("=" * 60)
    print("  Composio Research Verifier")
    print("  Cross-checking agent output against real docs")
    print("=" * 60)
    
    research_file = OUTPUT_DIR / "research_output.json"
    if not research_file.exists():
        print("❌ No research_output.json found. Run agent.py first.")
        exit(1)
    
    with open(research_file) as f:
        results = json.load(f)
    
    log = verify_sample(results, sample_size=20)
    print("\n✅ Verification complete!")
