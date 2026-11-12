"""Historical run identities belong to the run, not to later live configuration."""

import json

from agentproof.answers import AnswerRequest, AnswerService, ModelResponse, OpenAIAdapter


class NoEmbeddings:
    name = "test-disabled"
    status = "unavailable"

    def encode(self, _texts):
        return None


class Adapter:
    model = "local-draft"
    critic_model = "remote-reviewer"
    configured = True

    def configuration(self):
        return {"model": self.model, "critic_model": self.critic_model,
                "generator_provider": "local", "critic_provider": "openai"}

    def complete(self, _messages, *, purpose):
        assert purpose == "generate"
        return ModelResponse(json.dumps({"answer": "2023", "abstained": False,
                                        "citations": [{"source_id": "doc", "quote": "opened in 2023"}]}),
                             12, 8, 1, "stop", True)


def test_saved_run_retains_its_provider_identity(tmp_path):
    adapter = Adapter()
    runtime = AnswerService(tmp_path / "answers.sqlite3", adapter, NoEmbeddings())
    result = runtime.run(AnswerRequest(question="When did the service open?",
                                      sources=[{"id": "doc", "text": "The service opened in 2023."}],
                                      strategy="baseline", use_cache=False))
    adapter.critic_model = "new-configuration"
    assert result["critic_model"] == "remote-reviewer"
    assert result["generator_provider"] == "local"
    assert result["critic_provider"] == "openai"
    saved = runtime.store.get(result["id"])
    assert saved["critic_model"] == "remote-reviewer"
    assert saved["model"] == "local-draft"


def test_configuration_records_only_sent_sampling_parameters():
    adapter = OpenAIAdapter(base_url="http://127.0.0.1:8089/v1", model="local",
                            critic_base_url="https://api.openai.com/v1",
                            critic_model="gpt-5.4-mini-2026-03-17", enable_paid=True)
    assert adapter.configuration()["temperature"] == 0
    assert adapter.configuration()["critic_temperature"] is None
    hosted = OpenAIAdapter(base_url="https://api.openai.com/v1",
                           model="gpt-5.4-mini-2026-03-17", enable_paid=True)
    assert hosted.configuration()["temperature"] is None
