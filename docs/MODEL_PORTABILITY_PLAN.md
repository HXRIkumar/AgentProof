# Second-family local-model verification

Declared before any Phi benchmark trials on 12 November 2026. This is an adapter
and guarded-workflow portability check on existing authored cases. It is not a
new blind benchmark, model leaderboard or claim about untested providers.

Use `mlx-community/Phi-4-mini-instruct-4bit`, revision
`ac1c269cb4222a4e136a3d09edad301056c1f36a`, on the same Apple M4/24 GiB Mac with
MLX-LM 0.32.2 / MLX 0.32.4. The public community conversion is about 2.16 GB and
uses safetensors; no paid endpoint or remote model Python code is required.
Sources: [conversion](https://huggingface.co/mlx-community/Phi-4-mini-instruct-4bit)
and [Microsoft model card](https://huggingface.co/microsoft/Phi-4-mini-instruct).
The choice provides another model family at a manageable local memory cost; it
does not imply that this older model is the newest or best available model.

## Frozen execution

- Backend from commit `c015617` with SHA-256
  `669224b930a1aebcd80e2f711c405ef303be157cf14bbec3d33ee7d3b92458fb`.
  Only this plan is added before execution. No prompts, labels or guard logic
  are changed in response to this model's outputs.
- Standard paired baseline/guarded experiments; guarded proposal budget three.
- Temperature 0, maximum 512 generated tokens, timeout 120 seconds, prompt
  cache disabled. No Qwen-specific thinking override is sent to Phi.
- Original 24-case suite first, two repeats per strategy: 96 trials. Then the
  unchanged 30-case challenge, two repeats per strategy: 120 trials. Preserve
  each report independently. Baseline/guarded order alternates by case/repeat
  through the ordinary experiment worker; fresh sandbox per trial.
- One common warm-up request before both studies, excluded from trial totals
  and saved separately with response diagnostics. The model snapshot is pinned
  locally; its identity is operator-recorded, not independently attested.
- Run only after the Qwen diagnostic probe finishes. One model process/client
  performs inference at a time. Other development activity remains a timing
  limitation. Pending approvals remain untouched before exports.

## Report every outcome

For each suite report baseline and guarded correct outcomes, defined effect
checks, actual HTTP attempts, reported token totals and available response
diagnostics. Include every failed case and the ordinary experiment gate result.
Retain malformed responses as failures; do not exclude or silently repair them.
Interrupted experiments remain partial and cannot establish a passing result.

Do not run the strict release comparator against Qwen reports: model identity
and generation metadata differ. Do not pool case counts with earlier Qwen studies
or call temperature-zero repeats independent tasks. Source/template and host
differences also prevent attributing any timing difference solely to the model.
If this model cannot load in the installed runtime, record that limitation and
preserve the failure; no paid fallback is authorized or needed.
