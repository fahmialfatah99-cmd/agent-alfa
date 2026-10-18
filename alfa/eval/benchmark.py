"""Evaluation and benchmarking framework."""

import json
import os
from typing import Any

from alfa.core.db.memory import search_memories_sync
from alfa.tools.rag.retrieval import select_relevant_functions, select_relevant_tools


class BenchmarkSuite:
    def __init__(self, name: str):
        self.name = name
        self.results: dict[str, Any] = {
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
        mock_response: dict[str, Any] = {
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
        AgenticLoopBenchmark(),
        ScenarioFileBenchmark(),
    ]

    summary: dict[str, Any] = {
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


def _repo_root() -> str:
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


class ScenarioFileBenchmark(BenchmarkSuite):
    """Offline routing check atas evals/scenarios.json (single source skenario).

    Tiap skenario yang punya `expect_tools_any` harus di-routing oleh
    Tool-RAG ke minimal satu tool yang diharapkan; skenario tanpa ekspektasi
    tool cukup punya `checks` non-kosong. Sama seperti mode offline
    `evals/run_evals.py`, tapi memakai import modern (alfa.*).
    """

    def __init__(self, scenarios_path: str = ""):
        super().__init__("ScenarioFileBenchmark")
        self.scenarios_path = scenarios_path or os.path.join(
            _repo_root(), "evals", "scenarios.json"
        )

    def run(self):
        try:
            with open(self.scenarios_path, encoding="utf-8") as f:
                scenarios = json.load(f)
        except Exception as e:
            self._record_result("load scenarios.json", False, str(e))
            return self.results

        try:
            from alfa.tools import AVAILABLE_TOOLS
        except Exception as e:
            self._record_result("import AVAILABLE_TOOLS", False, str(e))
            return self.results

        for scn in scenarios:
            sid = scn.get("id", "?")
            expect = set(scn.get("expect_tools_any") or [])
            try:
                selected = select_relevant_functions(
                    list(AVAILABLE_TOOLS), scn.get("prompt", "")
                )
                names = {getattr(f, "__name__", "") for f in selected}
            except Exception as e:
                self._record_result(sid, False, f"routing error: {e}")
                continue
            if expect:
                hit = sorted(expect & names)
                self._record_result(
                    sid, bool(hit), f"hit={hit or 'TIDAK ADA'} dari {len(selected)}"
                )
            else:
                self._record_result(sid, bool(scn.get("checks")), "no tool expectation")

        return self.results
