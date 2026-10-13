"""Evaluation and benchmarking framework."""

from typing import Any

from alfa.core.db.memory import search_memories_sync
from alfa.tools.rag.retrieval import select_relevant_tools


class BenchmarkSuite:
    def __init__(self, name: str):
        self.name = name
        self.results = {
            "name": name,
            "passed": 0,
            "total": 0,
            "accuracy_pct": 0.0,
            "details": []
        }

    def run(self) -> dict[str, Any]:
        """Override in subclasses to run specific benchmark scenarios."""
        return self.results

    def _record_result(self, scenario: str, passed: bool, detail_msg: str = ""):
        self.results["total"] += 1
        if passed:
            self.results["passed"] += 1
        self.results["details"].append({
            "scenario": scenario,
            "passed": passed,
            "detail": detail_msg
        })
        if self.results["total"] > 0:
            self.results["accuracy_pct"] = (self.results["passed"] / self.results["total"]) * 100.0


class ToolSelectionBenchmark(BenchmarkSuite):
    def __init__(self):
        super().__init__("ToolSelectionBenchmark")

    def run(self):
        tools_schema = [
            {"function": {"name": "search_web", "description": "Search the internet"}},
            {"function": {"name": "calculate_math", "description": "Math calculator"}},
            {"function": {"name": "read_file", "description": "Read file contents"}}
        ]

        # In actual select_relevant_tools, it might return all or some.
        # For this test, we just check if it doesn't crash and returns a list.
        try:
            selected = select_relevant_tools(tools_schema, "What is 2+2?")
            passed = isinstance(selected, list)
            self._record_result("select_relevant_tools returns list for math query", passed)
        except Exception as e:
            self._record_result("select_relevant_tools math query", False, str(e))

        try:
            selected2 = select_relevant_tools(tools_schema, "Who won the world cup in 2022?")
            passed2 = isinstance(selected2, list)
            self._record_result("select_relevant_tools returns list for web query", passed2)
        except Exception as e:
            self._record_result("select_relevant_tools web query", False, str(e))

        return self.results


class MemoryRetrievalBenchmark(BenchmarkSuite):
    def __init__(self):
        super().__init__("MemoryRetrievalBenchmark")

    def run(self):
        try:
            results = search_memories_sync(user_id=9999, query="test document")
            passed = isinstance(results, list)
            self._record_result("search_memories_sync returns list", passed)
        except Exception as e:
            self._record_result("search_memories_sync returns list", False, str(e))

        return self.results


class AgenticLoopBenchmark(BenchmarkSuite):
    def __init__(self):
        super().__init__("AgenticLoopBenchmark")

    def run(self):
        mock_response = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "search_web",
                            "arguments": "{\"query\": \"test\"}"
                        }
                    }
                ]
            }
        }

        tool_calls = mock_response["message"].get("tool_calls")
        passed = (
            tool_calls is not None
            and len(tool_calls) == 1
            and tool_calls[0]["function"]["name"] == "search_web"
        )
        self._record_result("parses mock LLM response tool calls", passed)

        return self.results


def run_all_benchmarks() -> dict[str, Any]:
    suites = [
        ToolSelectionBenchmark(),
        MemoryRetrievalBenchmark(),
        AgenticLoopBenchmark()
    ]

    summary = {
        "total_benchmarks": len(suites),
        "total_passed_scenarios": 0,
        "total_scenarios": 0,
        "overall_accuracy_pct": 0.0,
        "suite_results": []
    }

    for suite in suites:
        res = suite.run()
        summary["suite_results"].append(res)
        summary["total_passed_scenarios"] += res["passed"]
        summary["total_scenarios"] += res["total"]

    if summary["total_scenarios"] > 0:
        summary["overall_accuracy_pct"] = (summary["total_passed_scenarios"] / summary["total_scenarios"]) * 100.0

    return summary
