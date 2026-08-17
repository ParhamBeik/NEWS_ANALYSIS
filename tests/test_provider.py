import json

import pytest

from news_intel import pipeline
from news_intel.core import dag
from news_intel.prompts import ClassificationOutput, EvaluationOutput, SummaryOutput
from news_intel.providers import OpenAICompatibleProvider, ProviderResponse, Usage
from news_intel.sources import RawArticle


class Response:
    status_code = 200

    def __init__(self, content, usage):
        self._payload = {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}], "usage": usage}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class Session:
    def post(self, *args, **kwargs):
        return Response({"category": "other", "confidence": "متوسط", "rationale": "ok"}, {"prompt_tokens": 11, "completion_tokens": 7})


def test_provider_validates_json_and_records_reported_usage():
    provider = OpenAICompatibleProvider("gapgpt", "test", "https://example.test/v1", "secret", 3, 100, session=Session(), retry_delay=0)
    response = provider.classify(RawArticle(source="test", url="https://test/1", title="خبر"))
    assert response.data.category == "other"
    assert response.usage.tokens_in == 11
    assert response.usage.tokens_out == 7


def test_provider_does_not_retry_invalid_structured_output():
    class InvalidSession:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return Response({"category": "invalid", "confidence": "متوسط", "rationale": "ok"}, {})

    session = InvalidSession()
    provider = OpenAICompatibleProvider("gapgpt", "test", "https://example.test/v1", "secret", 3, 100, session=session, retry_delay=0)
    with pytest.raises(dag.Permanent, match="invalid structured output"):
        provider.classify(RawArticle(source="test", url="https://test/1", title="خبر"))
    assert session.calls == 1


class MeteredProvider:
    name = "fake"
    model = "fake-v1"
    supports_structured_output = True

    def _response(self, data):
        return ProviderResponse(data, Usage(10, 5, 0.01, self.name, self.model))

    def classify(self, article, examples=()):
        return self._response(ClassificationOutput(category="security/economics", confidence="زیاد", rationale="ok"))

    def evaluate(self, article, category, examples=()):
        return self._response(EvaluationOutput(confidence_occurrence="زیاد", gold_price_impact="زیاد", security_relevance="زیاد", gold_trend="نامطمئن", rationale="ok"))

    def summarize(self, article, examples=()):
        return self._response(SummaryOutput(optimized_title=article.title, one_line=article.title))


def test_pipeline_persists_provider_usage_in_node_events(conn):
    # A realistic headline: the quality gate rejects stubs like "خبر" before inference,
    # which is the point of the gate, but makes it a useless fixture for metering.
    article = RawArticle(
        source="test", url="https://test/1", title="حمله موشکی به تاسیسات نفتی کشور",
        lead="جزئیات حادثه", content="متن کامل خبر",
        published_at="2026-08-16T10:00:00+03:30",
    )
    pipeline.process(conn, [article], MeteredProvider(), run_id="metered")
    events = conn.execute("SELECT tokens_in,tokens_out,cost_usd FROM node_events WHERE run_id='metered' ORDER BY id").fetchall()
    assert len(events) == 3
    assert sum(row["tokens_in"] for row in events) == 30
    assert sum(row["tokens_out"] for row in events) == 15
    assert sum(row["cost_usd"] for row in events) == 0.03
