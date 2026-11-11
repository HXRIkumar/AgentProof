# Why this project

Research checked 12 November 2026. This is a portfolio engineering project, not
evidence of production customer adoption or a guarantee of a particular salary.

## Signals from actual engineering roles

- [OpenAI Applied AI Engineer, Enterprise](https://openai.com/careers/applied-ai-engineer-enterprise-san-francisco/): evaluation harnesses, integration debugging, agent and tool design, reliability, observability, latency and cost.
- [Anthropic Applied AI Engineer, Enterprise](https://job-boards.greenhouse.io/anthropic/jobs/5057647008): Python/TypeScript, agents, evaluation frameworks, transcript analysis, MCP and deployment. These experienced-role expectations are a direction for learning, not credentials this project automatically confers.

My inference: an inspectable tool-agent runtime with meaningful failure tests is
a stronger demonstration of these skills than another conversational wrapper.
Framework popularity alone is weak evidence of engineering ability.

## Prior art and differentiation

[Anthropic's agent evaluation guide](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)
emphasizes grading the actual outcome, not just the transcript. [Sierra's
tau2-bench](https://github.com/sierra-research/tau2-bench) already evaluates
realistic tool interactions. AgentProof does not claim novelty in that category.
It focuses on a smaller inspectable failure laboratory: transaction ambiguity,
policy enforcement, human approval, and baseline/guarded release comparisons.

[LangGraph fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
explains why retrying a node cannot itself guarantee exactly-once side effects.
AgentProof makes this failure concrete in a local refund ledger. Its claim is
transactional deduplication in the tested SQLite sandbox, not exactly-once
delivery to a remote payment system.

## Technology choices

| Technology | Engineering purpose |
|---|---|
| Python, FastAPI, Pydantic | Typed experiment API and structured action boundary |
| LangGraph | Explicit observable workflow stages |
| SQLite | Reproducible local state, transactional ledger and persisted evidence |
| React, TypeScript, Vite | Interactive comparison and trace inspection |
| OpenTelemetry | Instrument real workflow spans; optional export |
| pytest, GitHub Actions | Repeatable regression gate |
| Docker | Single-service packaging with a persistent data volume |
| OpenAI-compatible HTTP adapter | Configurable hosted or local inference |

SQLite is intentional: a one-developer laboratory should be easy to run. It is
not a substitute for testing Postgres concurrency, a distributed job queue or
multi-tenant access control. Do not list those unimplemented systems on a resume.
MCP is a possible future interoperability layer, not an implemented feature.
No vector database is needed to validate a finite refund policy.

OpenTelemetry's [Python documentation](https://opentelemetry.io/docs/languages/python/)
and [GenAI conventions repository](https://github.com/open-telemetry/semantic-conventions-genai)
are the references; evolving GenAI conventions should not be called stable.

## What improves on the example harness

Semantic similarity and a critic's approval are insufficient for transactional
correctness. A fluent answer may still refund the wrong account. Here, evidence
includes ledger state, ownership, amount, approval and duplicate-write checks.
Caching is not counted as intelligence or recovery. Scripted fault tests and
real-model results are reported separately, with raw denominators and explicit
limits. More infrastructure is not automatically better; the project must make
one consequential workflow understandable and reproducible.
