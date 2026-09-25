"""
Phase 8 tests: the LangGraph agent end to end (with in-memory fakes), plus
its guardrails — tool registry, retry loop, budget, timeout.

The graph under test is the real compiled LangGraph graph; only the
retriever (search) and the LLM are fakes.
"""

import asyncio
import json

import pytest

from app.agents.errors import AgentTimeoutError
from app.agents.graph import AgentRunner, step_limit
from app.agents.prompts import clean_queries, parse_json_object
from app.agents.supervisor import needs_planning
from app.agents.tools.registry import Tool, ToolError, ToolRegistry
from app.core.config import Settings
from app.core.security import Permission, Role
from app.rag.reranker import HeuristicReranker
from tests.unit.test_rag import FakeLLM, chunk

NOTICE = chunk(1, clause="8.3", text="Notice must be given in writing to the registered office.")
FEES = chunk(2, clause="5.1", parent="p5", text="The Customer shall pay the Fees monthly.")
UNRELATED = chunk(3, clause="2.1", parent="p2", text="Headings are for convenience only.")


class QueryRetriever:
    """Returns hits chosen per query text; records every search."""

    def __init__(self, by_query=None, default=()):
        self.by_query = by_query or {}
        self.default = list(default)
        self.searches: list[str] = []

    async def retrieve(self, question, *, tenant_id, document_ids, version_ids, limit):
        assert tenant_id == "tenant-1"  # always the tenant from state
        self.searches.append(question)
        for key, hits in self.by_query.items():
            if key.lower() in question.lower():
                return list(hits)
        return list(self.default)

    async def parents(self, *, tenant_id, parent_ids):
        return {}


def runner(retriever, llm, **settings):
    return AgentRunner(retriever, HeuristicReranker(), llm, Settings(**settings))


async def ask(agent, question, history=None):
    return await agent.answer(question, tenant_id="tenant-1", role=Role.ANALYST, history=history)


def plan(standalone, subs, intent="qa"):
    return json.dumps({"intent": intent, "standalone_question": standalone, "sub_questions": subs})


# --- Planning ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "history", "expected"),
    [
        ("What is the notice period?", [], False),
        ("What is the notice period?", [("q", "a")], True),  # follow-up
        ("Compare the notice periods in the MSA and SOW", [], True),
        ("What do clauses 8.3 and 9.1 say?", [], True),
        ("Who pays? When?", [], True),
    ],
)
def test_planning_only_when_it_can_help(question, history, expected):
    assert needs_planning(question, history) is expected


def test_json_replies_are_parsed_strictly():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": 2} Hope that helps') == {"a": 2}
    assert parse_json_object("not json") is None
    assert parse_json_object("[1, 2]") is None
    assert clean_queries(["  a  b ", "A B", 3, "", "c"], limit=2) == ["a b", "c"]


async def test_simple_question_makes_one_model_call():
    llm = FakeLLM("Notices must be in writing [1].")
    result = await ask(runner(QueryRetriever(default=[NOTICE]), llm), "How are notices given?")
    assert len(llm.calls) == 1  # no planning call
    assert result.answer == "Notices must be in writing [1]." and result.citations
    assert [s.key for s in result.steps] == [
        "understand", "retrieve", "rerank", "validate", "context", "generate", "cite",
    ]  # fmt: skip
    assert (result.intent, result.queries, result.retries) == ("qa", ["How are notices given?"], 0)


async def test_follow_up_is_rewritten_before_searching():
    llm = FakeLLM(
        plan("What is the notice period for the Customer?", ["Customer notice period"]),
        "Thirty days [1].",
    )
    retriever = QueryRetriever(default=[NOTICE])
    history = [("What is the notice period for the Supplier?", "Sixty days [1].")]
    result = await ask(runner(retriever, llm), "And for the Customer?", history)
    assert retriever.searches == ["Customer notice period"]
    assert result.standalone_question == "What is the notice period for the Customer?"
    # The answer prompt asks the rewritten question and carries the history.
    final_prompt = llm.calls[-1]
    assert final_prompt[-1].content.endswith(
        "Question: What is the notice period for the Customer?"
    )
    assert [m.role for m in final_prompt] == ["system", "user", "assistant", "user"]


async def test_multi_part_question_searches_each_part():
    llm = FakeLLM(
        plan(
            "Compare notice (8.3) and payment (5.1)",
            ["notice requirements", "payment of fees"],
            intent="compare",
        ),
        "Notices are written [1]; fees are monthly [2].",
    )
    retriever = QueryRetriever({"notice": [NOTICE, UNRELATED], "fees": [FEES, UNRELATED]})
    result = await ask(runner(retriever, llm), "Compare clause 8.3 and clause 5.1")
    assert retriever.searches == ["notice requirements", "payment of fees"]
    assert {c.clause for c in result.citations} == {"8.3", "5.1"}  # both parts evidenced
    assert result.intent == "compare"


async def test_unusable_plan_falls_back_to_the_original_question():
    llm = FakeLLM("I think you should search for stuff", "Answer [1].")
    retriever = QueryRetriever(default=[NOTICE])
    result = await ask(runner(retriever, llm), "Compare notice terms?", [("q", "a")])
    assert retriever.searches == ["Compare notice terms?"]
    assert result.answer == "Answer [1]."


# --- Retry loop ----------------------------------------------------------------------------


async def test_weak_evidence_triggers_one_refined_search():
    llm = FakeLLM(
        json.dumps({"queries": ["termination notice in writing"]}),  # refine
        "Notices must be in writing [1].",
    )
    retriever = QueryRetriever({"termination": [NOTICE]}, default=[UNRELATED])
    result = await ask(runner(retriever, llm), "How do we end the deal?")
    assert retriever.searches == ["How do we end the deal?", "termination notice in writing"]
    assert result.retries == 1 and result.citations[0].clause == "8.3"
    assert "refine" in [s.key for s in result.steps]


async def test_retries_stop_when_no_new_wording_is_found():
    # The model keeps proposing the query that was already searched.
    llm = FakeLLM(json.dumps({"queries": ["How do we end the deal?"]}), "Not sure [1].")
    retriever = QueryRetriever(default=[UNRELATED])
    result = await ask(runner(retriever, llm, agent_max_retries=5), "How do we end the deal?")
    assert retriever.searches == ["How do we end the deal?"]  # never repeated
    assert len(llm.calls) == 2  # one refine attempt, then the answer
    assert result.retries == 5  # loop closed immediately


async def test_nothing_in_scope_means_no_model_call_and_no_retry():
    llm = FakeLLM()
    result = await ask(runner(QueryRetriever(), llm), "What is the notice period?")
    assert result.insufficient_evidence and llm.calls == [] and result.retries == 0


# --- Guardrails ------------------------------------------------------------------------------


async def test_registry_injects_tenant_and_refuses_reserved_arguments():
    seen = {}

    async def tool(*, tenant_id, x):
        seen["tenant"] = tenant_id
        return x

    registry = ToolRegistry([Tool("t", "", Permission.QUERY_RUN, tool)], max_calls=2)
    assert (
        await registry.call(
            "t", tenant_id="tenant-1", role=Role.VIEWER, calls_so_far=0, arguments={"x": 1}
        )
        == 1
    )
    assert seen["tenant"] == "tenant-1"
    with pytest.raises(ToolError, match="may not set"):
        await registry.call(
            "t",
            tenant_id="tenant-1",
            role=Role.VIEWER,
            calls_so_far=0,
            arguments={"x": 1, "tenant_id": "tenant-2"},  # e.g. injected via model output
        )
    with pytest.raises(ToolError, match="budget"):
        await registry.call(
            "t", tenant_id="tenant-1", role=Role.VIEWER, calls_so_far=2, arguments={"x": 1}
        )
    with pytest.raises(ToolError, match="Unknown tool"):
        await registry.call("rm", tenant_id="t", role=Role.ADMIN, calls_so_far=0, arguments={})


async def test_registry_checks_the_callers_permission():
    admin_only = Tool("manage", "", Permission.USER_MANAGE, lambda **_: asyncio.sleep(0))
    registry = ToolRegistry([admin_only], max_calls=5)
    with pytest.raises(ToolError, match="may not use"):
        await registry.call("manage", tenant_id="t", role=Role.VIEWER, calls_so_far=0, arguments={})


async def test_tool_budget_limits_searches_but_still_answers():
    llm = FakeLLM(plan("q", ["notice", "fees", "headings"]), "Answer [1].")
    retriever = QueryRetriever({"notice": [NOTICE]}, default=[FEES])
    result = await ask(
        runner(retriever, llm, agent_max_tool_calls=1), "Compare notice, fees and headings"
    )
    assert retriever.searches == ["notice"]  # budget of 1 search
    assert result.tool_calls == 1 and result.answer == "Answer [1]."


async def test_whole_run_has_a_time_limit():
    class SlowLLM(FakeLLM):
        async def generate(self, messages, **kwargs):
            await asyncio.sleep(5)

    with pytest.raises(AgentTimeoutError):
        await ask(
            runner(QueryRetriever(default=[NOTICE]), SlowLLM(), agent_timeout_s=0.05),
            "How are notices given?",
        )


def test_step_limit_covers_every_legitimate_path():
    # understand + 4 per search round + 3 answer nodes must fit.
    for retries in range(4):
        assert step_limit(retries) >= 1 + 4 * (retries + 1) + 3
