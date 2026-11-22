"""Quick verification of pipeline outputs."""
import pandas as pd
import json

df = pd.read_csv("data/outputs/fixtures/divergences.csv")
print("=== DIVERGENCE RECORDS (first 12) ===")
for _, r in df.head(12).iterrows():
    path = str(r["config_path"])[:42]
    cat = str(r["category"])[:18]
    dtype = str(r["diff_type"])[:18]
    conf = str(r["confidence"])[:8]
    is_def = r["is_from_default"]
    print(f"  {path:44s} {cat:20s} {dtype:20s} {conf:8s} default:{is_def}")

print(f"\n=== TOTAL: {len(df)} divergences across {df['env_pair'].nunique()} env pair(s) ===")
print(f"=== Comparable paths: {df['total_comparable_paths'].max()} ===")
print(f"=== Categories: {dict(df['category'].value_counts())} ===")
print(f"=== Diff types: {dict(df['diff_type'].value_counts())} ===")
print(f"=== Confidence: {dict(df['confidence'].value_counts())} ===")
print(f"=== From defaults: {int(df['is_from_default'].sum())}/{len(df)} ===")
print(f"=== Redacted: {int(df['redacted'].sum())}/{len(df)} ===")

# Check metrics
with open("data/outputs/fixtures/snapshot_metrics.json") as f:
    metrics = json.load(f)
print(f"\n=== METRICS ===")
print(f"  Raw density: {metrics['raw_divergence_density']}")
print(f"  High confidence: {metrics['high_confidence_count']}")
print(f"  Env-specific: {metrics['typically_env_specific_count']}")
