# Stage 3 Adversarial Guardrail Set

This directory contains a small Stage 3 adversarial evaluation slice focused on
guardrail-sensitive cases that should be kept stable over time:

- `hard_negative`
- `prompt_injection`
- `pii_trap`

Files:
- `manifest.json`: aggregate metadata for the combined stage3 adversarial set
- `hard_negative.jsonl`: entity-correct-but-fact-wrong distractor cases
- `prompt_injection.jsonl`: indirect prompt injection / instruction override attempts
- `pii_trap.jsonl`: output-side PII leakage traps that should force abstain/refusal
