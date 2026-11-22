"""Run eligibility assessment on all cloned repos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.logging_config import setup_logging
from src.discovery.eligibility import assess_eligibility, batch_assess

setup_logging(level="INFO")

repos_dir = Path("data/repos")
output_path = Path("data/processed/eligibility_assessment")

assessments = []
for repo_dir in sorted(repos_dir.iterdir()):
    if not repo_dir.is_dir() or repo_dir.name.startswith("."):
        continue

    print(f"\nAssessing: {repo_dir.name}")
    result = assess_eligibility(
        repo_path=repo_dir,
        repo_id=f"github/{repo_dir.name}",
        min_environments=1,  # Allow single env + defaults
        min_stars=0,  # We already cloned these
        allow_single_env_with_defaults=True,
    )
    assessments.append(result)

    status = "✅ ELIGIBLE" if result["eligible"] else "❌ EXCLUDED"
    reasons = "; ".join(result.get("exclusion_reasons", []))
    envs = result.get("environment_evidence", {})
    print(f"  {status} {reasons}")
    if envs:
        for chart, info in envs.items():
            print(f"    Chart '{chart}': {info['environments']}")

# Save
df = batch_assess(assessments, output_path)
print(f"\n{'='*60}")
print(f"ELIGIBILITY SUMMARY: {df['eligible'].sum()}/{len(df)} eligible")
print(f"{'='*60}")
print(df.to_string(index=False))
