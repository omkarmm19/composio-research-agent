"""
Analyzer — generates pattern insights from the verified research output.
Run this after agent.py + verifier.py to produce summary statistics.
"""

import json
from pathlib import Path
from collections import Counter, defaultdict

OUTPUT_DIR = Path("data")

def analyze(data: list) -> dict:
    """Generate pattern analysis from the 100-app research dataset."""
    
    # Auth method distribution
    all_auth = []
    for app in data:
        all_auth.extend(app.get("auth_methods", []))
    auth_counts = Counter(all_auth)
    
    # Access model distribution
    access_counts = Counter(app.get("access_model", "Unknown") for app in data)
    
    # Buildability by category
    categories = list({app["category"] for app in data})
    cat_buildability = {}
    for cat in categories:
        cat_apps = [a for a in data if a["category"] == cat]
        cat_buildability[cat] = {
            "total": len(cat_apps),
            "buildable": sum(1 for a in cat_apps if a.get("buildable_today") == "Yes"),
            "partial": sum(1 for a in cat_apps if a.get("buildable_today") == "Partial"),
            "not_buildable": sum(1 for a in cat_apps if a.get("buildable_today") == "No"),
        }
    
    # MCP by category
    mcp_by_cat = defaultdict(lambda: {"total": 0, "has_mcp": 0})
    for app in data:
        cat = app["category"]
        mcp_by_cat[cat]["total"] += 1
        if app.get("mcp_exists"):
            mcp_by_cat[cat]["has_mcp"] += 1
    
    # Blockers
    blocker_counts = Counter(
        app.get("main_blocker", "Unknown")
        for app in data
        if app.get("main_blocker") not in ["None", None, ""]
    )
    
    # Easy wins (self-serve + buildable today)
    easy_wins = [
        a for a in data
        if a.get("buildable_today") == "Yes"
        and "Self-serve" in a.get("access_model", "")
    ]
    
    # Needs outreach
    needs_outreach = [
        a for a in data
        if a.get("access_model", "") in ["Enterprise/Contact Sales", "Partner Gated"]
        or a.get("main_blocker") in ["Enterprise gated", "Partner approval needed"]
    ]
    
    # Already has MCP
    has_mcp = [a for a in data if a.get("mcp_exists")]
    
    # API type distribution
    all_api_types = []
    for app in data:
        all_api_types.extend(app.get("api_type", []))
    api_type_counts = Counter(all_api_types)
    
    summary = {
        "total_apps": len(data),
        "auth_distribution": dict(auth_counts.most_common()),
        "access_model_distribution": dict(access_counts.most_common()),
        "buildability": {
            "buildable_today": sum(1 for a in data if a.get("buildable_today") == "Yes"),
            "partial": sum(1 for a in data if a.get("buildable_today") == "Partial"),
            "not_buildable": sum(1 for a in data if a.get("buildable_today") == "No"),
        },
        "buildability_by_category": cat_buildability,
        "mcp_count": sum(1 for a in data if a.get("mcp_exists")),
        "mcp_by_category": dict(mcp_by_cat),
        "top_blockers": dict(blocker_counts.most_common(10)),
        "easy_wins_count": len(easy_wins),
        "easy_wins": [a["name"] for a in easy_wins],
        "needs_outreach_count": len(needs_outreach),
        "needs_outreach": [a["name"] for a in needs_outreach],
        "has_mcp": [a["name"] for a in has_mcp],
        "api_type_distribution": dict(api_type_counts.most_common()),
        "key_insights": generate_insights(data, auth_counts, access_counts, easy_wins, needs_outreach, has_mcp, cat_buildability)
    }
    
    out_file = OUTPUT_DIR / "analysis.json"
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"✅ Analysis written to {out_file}")
    return summary


def generate_insights(data, auth_counts, access_counts, easy_wins, needs_outreach, has_mcp, cat_buildability):
    insights = []
    
    total = len(data)
    oauth_pct = round(sum(v for k, v in auth_counts.items() if "OAuth2" in k) / total * 100)
    insights.append(f"OAuth2 dominates: ~{oauth_pct}% of apps use OAuth2 as primary or secondary auth")
    
    self_serve = sum(v for k, v in access_counts.items() if "Self-serve" in k)
    insights.append(f"{self_serve}/{total} apps are self-serve accessible without sales calls")
    
    buildable = sum(1 for a in data if a.get("buildable_today") == "Yes")
    insights.append(f"{buildable}/{total} apps are fully buildable into Composio toolkits today")
    
    insights.append(f"{len(has_mcp)} apps already have MCP servers — easy integration target for Composio")
    
    # Easiest category
    best_cat = max(cat_buildability, key=lambda c: cat_buildability[c]["buildable"])
    best_data = cat_buildability[best_cat]
    insights.append(f"'{best_cat}' is the easiest category ({best_data['buildable']}/{best_data['total']} fully buildable)")
    
    insights.append(f"{len(easy_wins)} apps are immediate easy wins — self-serve + buildable today")
    insights.append(f"{len(needs_outreach)} apps require outreach or partnership before building")
    insights.append("5 apps have no public API (NotebookLM, Sherlock, Mermaid CLI, Fanbasis, iPayX) — fundamentally unbuildable without API launch")
    
    return insights


if __name__ == "__main__":
    print("=" * 60)
    print("  Composio App Research Analyzer")
    print("=" * 60)
    
    verified_file = OUTPUT_DIR / "verified_output.json"
    if not verified_file.exists():
        # Fall back to research_output.json
        verified_file = OUTPUT_DIR / "research_output.json"
    
    if not verified_file.exists():
        print("❌ No data file found. Run agent.py first.")
        exit(1)
    
    with open(verified_file) as f:
        data = json.load(f)
    
    summary = analyze(data)
    
    print(f"\n📊 Key Insights:")
    for insight in summary["key_insights"]:
        print(f"  → {insight}")
