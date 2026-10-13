"""Tests for rate limiter and evaluation framework."""

from alfa.core.rate_limiter import (
    check_rate_limit,
    get_cost_estimate,
    get_user_usage_today,
    set_user_budget,
)
from alfa.eval.benchmark import (
    AgenticLoopBenchmark,
    BenchmarkSuite,
    MemoryRetrievalBenchmark,
    ToolSelectionBenchmark,
    run_all_benchmarks,
)


def test_get_cost_estimate():
    result = get_cost_estimate("test " * 100, "gpt-4")
    assert result["estimated_tokens"] >= 25
    assert result["estimated_cost_usd"] > 0

    result2 = get_cost_estimate("test " * 100, "gpt-3.5-turbo")
    assert result2["estimated_tokens"] >= 25
    assert result2["estimated_cost_usd"] > 0
    assert result["estimated_cost_usd"] > result2["estimated_cost_usd"]

def test_set_and_get_user_budget():
    test_user_id = 99991
    set_user_budget(test_user_id, 1000, 50)
    usage = get_user_usage_today(test_user_id)
    assert usage["budget_limit"] == 1000
    assert usage["call_limit"] == 50

def test_check_rate_limit_within_budget():
    test_user_id = 99992
    set_user_budget(test_user_id, 99999999, 99999999)
    allowed, reason = check_rate_limit(test_user_id)
    # Depending on how much usage is stored globally today,
    # it's possible it exceeds even 99M if someone spammed, but extremely unlikely.
    assert allowed is True
    assert reason == "OK"

def test_check_rate_limit_exceeded_calls():
    test_user_id = 99993
    # If we set call limit to 0 and we have made any calls globally today, or even 0 calls,
    # if total_calls >= 0, it will trigger limit.
    set_user_budget(test_user_id, 99999999, 0)
    allowed, reason = check_rate_limit(test_user_id)
    assert allowed is False
    assert "Daily call limit reached" in reason

def test_benchmark_suite_base():
    suite = BenchmarkSuite("TestBase")
    res = suite.run()
    assert res["name"] == "TestBase"
    assert res["passed"] == 0
    assert res["total"] == 0

    suite._record_result("test1", True)
    assert suite.results["passed"] == 1
    assert suite.results["total"] == 1

def test_tool_selection_benchmark():
    suite = ToolSelectionBenchmark()
    res = suite.run()
    assert res["name"] == "ToolSelectionBenchmark"
    assert res["total"] == 2
    assert res["passed"] <= res["total"]

def test_memory_retrieval_benchmark():
    suite = MemoryRetrievalBenchmark()
    res = suite.run()
    assert res["name"] == "MemoryRetrievalBenchmark"
    assert res["total"] == 1

def test_agentic_loop_benchmark():
    suite = AgenticLoopBenchmark()
    res = suite.run()
    assert res["name"] == "AgenticLoopBenchmark"
    assert res["total"] == 1
    assert res["passed"] == 1

def test_run_all_benchmarks():
    summary = run_all_benchmarks()
    assert summary["total_benchmarks"] == 3
    assert summary["total_scenarios"] == 4
    assert summary["overall_accuracy_pct"] >= 0.0
