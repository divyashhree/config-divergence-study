# Annotation Guide for Configuration Divergence Classification

## Purpose

This guide instructs independent reviewers on how to classify configuration divergences identified by the automated analysis pipeline. The goal is to determine whether each observed difference between environments is **intentional** (expected variation) or **potentially accidental** (unintended inconsistency).

## Important Principles

1. **You are classifying intent, not severity.** A difference may be intentional even if it looks unusual. A difference may be accidental even if it appears harmless.

2. **Use available evidence.** Base your classification on the configuration context, documentation, commit history, and common Kubernetes practices — not on assumption alone.

3. **When uncertain, say so.** The "undetermined" label exists for cases where you cannot make a confident judgment. Using it is not a failure.

4. **Do not consult other reviewers' labels.** Your labels must be independent for the agreement analysis to be valid.

## Classification Labels

### Intentional
The difference is expected and appropriate for the target environment.

**Examples:**
- Production has more replicas than development
- Production has stricter resource limits
- Different image tags across environments
- TLS enabled only in production
- Debug logging enabled only in development
- Different hostnames or ingress rules per environment

**Evidence patterns:**
- The category is "typically environment-specific" (replica_scaling, resource_limits, image_version, networking, feature_flag)
- The values follow a logical pattern (prod > dev for resources, dev has debug, prod has TLS)
- Chart documentation or comments explain the variation

### Accidental (Strong Evidence)
There is evidence that the difference was not intended.

**Examples:**
- A value appears to be a copy-paste error (e.g., dev hostname in production config)
- A commit message or PR mentions fixing this exact misconfiguration
- One environment has a value that contradicts its own documentation
- A key was added in one environment but clearly should apply to all

**Evidence requirements:**
- You must cite specific evidence (commit SHA, PR, comment, documentation conflict)
- "It looks wrong" is not sufficient — that belongs in "suspicious"

### Suspicious (Unconfirmed)
The difference looks potentially problematic but you lack definitive evidence.

**Examples:**
- Health check parameters differ between environments with no obvious reason
- Security settings are weaker in production than in staging
- An environment variable is present in one env but missing in another, with no clear reason
- A value seems inconsistent but you cannot find documentation either way

**When to use:**
- You would want to ask the maintainer about it
- The category is "typically consistent" (health_check, security) but you can't confirm it's wrong

### Undetermined
Insufficient information to classify.

**When to use:**
- You don't understand the configuration parameter
- The context is too complex to assess
- Both intentional and accidental interpretations are equally plausible
- The value was redacted (secrets) and you cannot assess it

## Annotation Procedure

1. **Review the divergence record:** Read the config path, values in each environment, diff type, category, and evidence notes.

2. **Check the category guidance:** Note whether the category is "typically environment-specific" or "typically consistent."

3. **Examine source files:** If available, look at the actual values files and chart defaults.

4. **Check commit history:** If a commit SHA is provided, look at the commit message and surrounding changes.

5. **Assign a label:** Choose one of the four labels above.

6. **Write your reasoning:** Explain in 1-3 sentences why you chose this label. Be specific.

7. **Record evidence references:** List any commit SHAs, file paths, or URLs that support your decision.

## Recording Format

For each divergence case, record:

| Field | Description |
|---|---|
| `divergence_id` | The unique ID from the divergence record (pre-filled) |
| `reviewer_id` | Your reviewer identifier |
| `label` | One of: intentional, accidental, suspicious, undetermined |
| `reasoning` | 1-3 sentence explanation |
| `evidence_refs` | Comma-separated commit SHAs, URLs, or file paths |

## Worked Examples

### Example 1: Replica Count

```
Path: replicaCount
Env A (dev): 1
Env B (prod): 3
Category: replica_scaling (typically env-specific)
```

**Label:** Intentional
**Reasoning:** Production running more replicas than development is standard practice for availability. The replica_scaling category is typically environment-specific.

### Example 2: Health Check Path

```
Path: livenessProbe.httpGet.path
Env A (staging): /healthz
Env B (prod): /health
Category: health_check (typically consistent)
```

**Label:** Suspicious
**Reasoning:** Health check paths should typically be the same across environments. The slight difference (/healthz vs /health) could indicate a copy-paste error or an intentional endpoint change. No commit evidence available to confirm.

### Example 3: Password in Config

```
Path: database.password
Env A (dev): [REDACTED]
Env B (prod): [REDACTED]
Category: security
```

**Label:** Undetermined
**Reasoning:** Values are redacted. Cannot assess whether the difference is intentional (different credentials per environment is expected) or accidental.

## Common Pitfalls

- **Don't assume every difference is a bug.** Most differences between environments are intentional.
- **Don't assume "typically env-specific" means always intentional.** A wrong replica count in production is still accidental.
- **Don't use "accidental" without evidence.** If you just suspect it, use "suspicious."
- **Don't skip the reasoning field.** It's needed for the agreement analysis and adjudication.
