"""
Composio Research Agent
=======================
Researches 100 apps to determine auth methods, API surface, MCP availability,
self-serve vs gated access, and buildability for Composio agent toolkits.

Uses Google Gemini Flash with Google Search grounding.
"""

import json
import os
import time
import re
from pathlib import Path
import google.generativeai as genai
from google.generativeai import types

# ─── Config ───────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_NAME = "gemini-2.0-flash"
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

# Rate limiting: stay under free tier (15 req/min, 1500 req/day)
DELAY_BETWEEN_REQUESTS = 5  # seconds

RESEARCH_PROMPT_TEMPLATE = """
You are a developer relations researcher at Composio. Composio builds agent toolkits that let AI agents call external app APIs. 

Research the following app and return ONLY a valid JSON object (no markdown, no explanation):

App: {app_name}
Website/Hint: {hint}
Category: {category}

Return this exact JSON structure:
{{
  "id": {id},
  "name": "{app_name}",
  "category": "{category}",
  "what_it_does": "<one clear line describing what the app does>",
  "auth_methods": ["<list of: OAuth2, API key, Basic Auth, Bearer token, Bot token, or Other>"],
  "access_model": "<Self-serve Free | Self-serve Trial | Paid Plan Required | Enterprise/Contact Sales | Partner Gated | Mixed>",
  "access_notes": "<brief explanation of credential requirements>",
  "api_type": ["<REST | GraphQL | WebSocket | CLI only | No Public API>"],
  "api_breadth": "<Comprehensive | Moderate | Limited | None>",
  "api_capabilities": "<brief description of what the API can do>",
  "mcp_exists": <true|false>,
  "mcp_notes": "<MCP server details or 'No official MCP server found'>",
  "buildable_today": "<Yes | Partial | No>",
  "main_blocker": "<None | Paid plan required | Enterprise gated | Partner approval needed | No public API | App review required | Limited API surface | Unclear documentation>",
  "evidence_url": "<primary documentation URL>",
  "confidence": "<High | Medium | Low>"
}}

Research guidelines:
- Check the official developer docs / API docs
- Look for existing MCP servers (model context protocol) on their site or GitHub
- For auth: check what developers actually need to get started
- For self-serve: can a dev get working credentials TODAY for free or trial?
- Be honest - if it's gated or has no public API, say so
- Evidence URL must be a real URL to their actual API documentation
"""

def research_app(client, app: dict) -> dict:
    """Research a single app using Gemini with Google Search grounding."""
    prompt = RESEARCH_PROMPT_TEMPLATE.format(
        id=app["id"],
        app_name=app["name"],
        hint=app["hint"],
        category=app["category"]
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
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()
        
        result = json.loads(text)
        print(f"  ✅ {app['name']} — {result.get('buildable_today', '?')} | {result.get('main_blocker', '?')}")
        return result
        
    except json.JSONDecodeError as e:
        print(f"  ⚠️  {app['name']} — JSON parse error: {e}")
        return _fallback_entry(app, f"JSON parse error: {e}")
    except Exception as e:
        print(f"  ❌ {app['name']} — Error: {e}")
        return _fallback_entry(app, str(e))


def _fallback_entry(app: dict, error: str) -> dict:
    """Return a skeleton entry when the agent fails."""
    return {
        "id": app["id"],
        "name": app["name"],
        "category": app["category"],
        "what_it_does": "Research failed",
        "auth_methods": ["Unknown"],
        "access_model": "Unknown",
        "access_notes": f"Error: {error}",
        "api_type": ["Unknown"],
        "api_breadth": "Unknown",
        "api_capabilities": "Research failed",
        "mcp_exists": False,
        "mcp_notes": "Unknown",
        "buildable_today": "No",
        "main_blocker": "Research error",
        "evidence_url": "",
        "confidence": "Low"
    }


def run_research(apps: list, resume: bool = True) -> list:
    """Run the research agent across all apps."""
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY environment variable not set.\n"
            "Get a free key at: https://aistudio.google.com/apikey"
        )
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Load existing results for resume capability
    output_file = OUTPUT_DIR / "research_output.json"
    results = {}
    if resume and output_file.exists():
        with open(output_file) as f:
            existing = json.load(f)
            results = {r["id"]: r for r in existing}
        print(f"📂 Resuming — {len(results)} apps already researched")
    
    total = len(apps)
    for i, app in enumerate(apps, 1):
        if resume and app["id"] in results:
            print(f"⏭️  [{i}/{total}] Skipping {app['name']} (already done)")
            continue
        
        print(f"🔍 [{i}/{total}] Researching {app['name']} ({app['category']})...")
        result = research_app(client, app)
        results[app["id"]] = result
        
        # Save after every app (crash recovery)
        with open(output_file, "w") as f:
            json.dump(list(results.values()), f, indent=2)
        
        # Rate limiting
        if i < total:
            time.sleep(DELAY_BETWEEN_REQUESTS)
    
    final = sorted(results.values(), key=lambda x: x["id"])
    with open(output_file, "w") as f:
        json.dump(final, f, indent=2)
    
    print(f"\n✅ Research complete. Output: {output_file}")
    return final


if __name__ == "__main__":
    print("=" * 60)
    print("  Composio App Research Agent")
    print("  Powered by Gemini Flash + Google Search Grounding")
    print("=" * 60)
    
    with open("apps.json") as f:
        apps = json.load(f)
    
    print(f"\n📋 Loaded {len(apps)} apps across 10 categories")
    print("🤖 Starting research agent...\n")
    
    results = run_research(apps, resume=True)
    
    print(f"\n📊 Summary:")
    buildable = sum(1 for r in results if r.get("buildable_today") == "Yes")
    partial = sum(1 for r in results if r.get("buildable_today") == "Partial")
    not_buildable = sum(1 for r in results if r.get("buildable_today") == "No")
    mcp_count = sum(1 for r in results if r.get("mcp_exists"))
    print(f"  ✅ Buildable today: {buildable}/100")
    print(f"  🔶 Partial (needs work): {partial}/100")
    print(f"  ❌ Not buildable: {not_buildable}/100")
    print(f"  🔌 Has existing MCP: {mcp_count}/100")
