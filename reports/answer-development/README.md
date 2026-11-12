# Retained development experiments

These records show development iterations before the 64-case evaluation. They are not held-out performance claims. Earlier protocols and validators differ; do not pool their results. Failed and interrupted runs are retained. Source passages derived from SQuAD retain the attribution and CC BY-SA 4.0 terms documented in [the dataset card](../../examples/answer-suite-v1/README.md).

| Run | Status | Cases | Direct / validated / adaptive correct | SHA-256 |
| --- | --- | ---: | --- | --- |
| [answers-dev-cascade-v1](answers-dev-cascade-v1.json) | completed | 18 | 11 / 12 / 15 | `b8a2eb2798ba473eee9b068c9f1a7c17987ec6fca07c31f8d4614ea8f524ff09` |
| [answers-dev-hybrid-medium-v1](answers-dev-hybrid-medium-v1.json) | completed | 18 | 11 / 12 / 14 | `1deca4e616df3500490c08d1c81f92f6004174ee3c88b3d76de774c24af9749f` |
| [answers-dev-hybrid-v1](answers-dev-hybrid-v1.json) | completed | 18 | 11 / 12 / 13 | `6ff63b32447c069949e7c991a2a00782e9e7f32de4889cf22c986ba38b7f3a9d` |
| [answers-dev-mini-v1](answers-dev-mini-v1.json) | completed | 18 | 13 / 13 / 13 | `09f65b96c5c4dde457a17bf0388e49d653444ab63afccb051639cd8a963d01bb` |
| [answers-dev-qwen-thinking-v1](answers-dev-qwen-thinking-v1.json) | interrupted | 18 | 0 / 0 / 0 | `c86ea1218c9bdf59128812ed96b4c70c99e71bf04c9e30e7b4e21ab6bc3ec33b` |
| [answers-dev-qwen-v1](answers-dev-qwen-v1.json) | completed | 6 | 1 / 1 / 2 | `9bea5096c0808e990db3a69e9214d575a0cef0595045d91997b13f33e51cc15a` |
| [answers-dev-qwen-v2](answers-dev-qwen-v2.json) | completed | 18 | 6 / 10 / 8 | `d7c4aa64eebc1078b5f563d1b6b0236e0173a41465545b172d92e5343045e852` |
| [answers-dev-qwen-v3](answers-dev-qwen-v3.json) | completed | 18 | 11 / 11 / 9 | `b08dbf550e02ad76bc829b72c51e40c23540a99e3809e6908c90e464d57ba631` |
| [answers-dev-qwen-v4](answers-dev-qwen-v4.json) | completed | 18 | 11 / 12 / 13 | `b1006742d7c8bd9663b725a865bc1da4dd7049c693b3c5bd64d534a01b7bc1ef` |

The local thinking diagnostic was interrupted after a contract defect and a transport timeout were identified; its partial coverage is not a final comparison. `qwen-v2` predates extraction normalization; `qwen-v3` predates the corrected abstention contract. `qwen-v4` fixes both and duplicate-key feedback. The hybrid runs then compare efficient hosted critic settings; `cascade-v1` enables final-attempt escalation.

The final selected configuration uses the same pinned mini model at medium reasoning, with optional selective escalation compared separately. Improvements shown in these development records motivated that choice; confirmation uses the frozen evaluation split.
