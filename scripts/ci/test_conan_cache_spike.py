"""Tests for credential-free Conan download-cache Spike evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.ci.conan_cache_spike import collect, compare_results


GIB = 1024**3


class ConanCacheSpikeTests(unittest.TestCase):
    """Exercise collection, comparison, and command-line reporting."""

    def _graph(
        self,
        path: Path,
        *,
        ref: str = "zlib/1.3.2#recipe",
        package_id: str = "pkg-id",
        context: str = "host",
        binary: str = "Cache",
    ) -> None:
        path.write_text(
            json.dumps(
                {
                    "graph": {
                        "nodes": {
                            "0": {
                                "ref": "conanfile",
                                "package_id": None,
                                "context": "host",
                            },
                            "1": {
                                "ref": ref,
                                "rrev": "recipe",
                                "package_id": package_id,
                                "prev": "package-revision",
                                "context": context,
                                "binary": binary,
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def _collection_inputs(self, root: Path) -> tuple[Path, Path, Path]:
        cache = root / "cache"
        cache.mkdir()
        (cache / "nested").mkdir()
        (cache / "archive.tgz").write_bytes(b"archive")
        (cache / "nested" / "metadata.txt").write_bytes(b"meta")
        graph = root / "graph.json"
        self._graph(graph)
        log = root / "build.log"
        log.write_text(
            "Build started\nConan install elapsed: 12.5s\nBuild completed\n",
            encoding="utf-8",
        )
        return cache, graph, log

    def _samples(self) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        common = {
            "graph_digest": "a" * 64,
            "source_builds": [],
            "cache_bytes": 1000,
        }
        cold = {
            **common,
            "role": "baseline",
            "cache_hit": False,
            "restore_seconds": 1.0,
            "conan_install_seconds": 199.0,
        }
        warm = [
            {
                **common,
                "role": "baseline",
                "cache_hit": True,
                "restore_seconds": 5.0,
                "conan_install_seconds": install,
            }
            for install in (15.0, 20.0, 25.0)
        ]
        recovery = {
            **common,
            "role": "recovery",
            "cache_hit": False,
            "restore_seconds": 1.0,
            "conan_install_seconds": 205.0,
        }
        return cold, warm, recovery

    def _run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "scripts.ci.conan_cache_spike", *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_collect_emits_stable_safe_identity_and_timing_math(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)

            first = collect(cache, graph, log, build_total_seconds=20.0)
            payload = json.loads(graph.read_text(encoding="utf-8"))
            payload["graph"]["nodes"] = {
                "9": payload["graph"]["nodes"]["1"],
                "3": payload["graph"]["nodes"]["0"],
            }
            graph.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            second = collect(cache, graph, log, build_total_seconds=20.0)

            self.assertEqual(first, second)
            self.assertEqual(
                set(first),
                {
                    "cache_bytes",
                    "cache_files",
                    "conan_install_seconds",
                    "graph_digest",
                    "package_count",
                    "project_build_seconds",
                    "source_builds",
                },
            )
            self.assertEqual(first["cache_bytes"], 11)
            self.assertEqual(first["cache_files"], 2)
            self.assertEqual(first["package_count"], 1)
            self.assertEqual(first["source_builds"], [])
            self.assertEqual(first["conan_install_seconds"], 12.5)
            self.assertEqual(first["project_build_seconds"], 7.5)
            self.assertEqual(len(first["graph_digest"]), 64)
            self.assertNotIn("zlib", json.dumps(first))

    def test_collect_clamps_project_build_time_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)

            result = collect(cache, graph, log, build_total_seconds=10.0)

            self.assertEqual(result["project_build_seconds"], 0.0)

    def test_collect_rejects_forbidden_config_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            (cache / "nested" / "CrEdEnTiAlS.JsOn").write_text(
                "must-not-leak", encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                collect(cache, graph, log, build_total_seconds=20.0)

    def test_collect_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            (cache / "nested" / "archive-link").symlink_to(cache / "archive.tgz")

            with self.assertRaisesRegex(RuntimeError, "symlink"):
                collect(cache, graph, log, build_total_seconds=20.0)

    def test_collect_rejects_empty_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            graph = root / "graph.json"
            self._graph(graph)
            log = root / "build.log"
            log.write_text("Conan install elapsed: 1s\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "no regular files"):
                collect(cache, graph, log, build_total_seconds=2.0)

    def test_collect_rejects_absent_or_non_directory_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "graph.json"
            self._graph(graph)
            log = root / "build.log"
            log.write_text("Conan install elapsed: 1s\n", encoding="utf-8")

            with self.subTest("absent"):
                with self.assertRaisesRegex(RuntimeError, "not a directory"):
                    collect(root / "missing", graph, log, build_total_seconds=2.0)

            cache_file = root / "cache-file"
            cache_file.write_bytes(b"archive")
            with self.subTest("regular file"):
                with self.assertRaisesRegex(RuntimeError, "not a directory"):
                    collect(cache_file, graph, log, build_total_seconds=2.0)

    def test_collect_rejects_source_builds_without_exposing_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            sentinel = "sentinel-private-dependency/9.9#secret-revision"
            self._graph(graph, ref=sentinel, binary="bUiLd")

            with self.assertRaises(RuntimeError) as context:
                collect(cache, graph, log, build_total_seconds=20.0)

            message = str(context.exception)
            self.assertRegex(message, r"source builds for 1 dependenc(?:y|ies)")
            self.assertNotIn(sentinel, message)

    def test_collect_rejects_missing_exact_timing_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            log.write_text(
                "prefix Conan install elapsed: 12s\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "timing"):
                collect(cache, graph, log, build_total_seconds=20.0)

    def test_graph_digest_changes_with_package_id_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            original = collect(cache, graph, log, build_total_seconds=20.0)

            self._graph(graph, package_id="different-package-id")
            changed_package = collect(cache, graph, log, build_total_seconds=20.0)
            self._graph(graph, context="build")
            changed_context = collect(cache, graph, log, build_total_seconds=20.0)

            self.assertNotEqual(original["graph_digest"], changed_package["graph_digest"])
            self.assertNotEqual(original["graph_digest"], changed_context["graph_digest"])

    def test_compare_accepts_five_run_fixture(self) -> None:
        cold, warm, recovery = self._samples()

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "accept")
        self.assertEqual(verdict["improvement_percent"], 87.5)
        self.assertEqual(verdict["cold_prep_seconds"], 200.0)
        self.assertEqual(verdict["warm_prep_seconds"], [20.0, 25.0, 30.0])
        self.assertEqual(verdict["warm_median_seconds"], 25.0)
        self.assertEqual(verdict["warm_max_seconds"], 30.0)
        self.assertEqual(verdict["largest_cache_bytes"], 1000)
        self.assertEqual(verdict["graph_digest"], "a" * 64)
        self.assertTrue(verdict["reasons"])

    def test_compare_rejects_graph_mismatch(self) -> None:
        cold, warm, recovery = self._samples()
        recovery["graph_digest"] = "b" * 64

        with self.assertRaisesRegex(RuntimeError, "graph digest"):
            compare_results([cold, *warm, recovery])

    def test_compare_rejects_source_build_result(self) -> None:
        cold, warm, recovery = self._samples()
        sentinel = "sentinel-private-dependency/8.8#secret-revision"
        warm[1]["source_builds"] = [sentinel]

        with self.assertRaises(RuntimeError) as context:
            compare_results([cold, *warm, recovery])

        message = str(context.exception)
        self.assertIn("source builds", message)
        self.assertNotIn(sentinel, message)

    def test_compare_rejects_malformed_sample_matrix(self) -> None:
        cold, warm, recovery = self._samples()
        malformed_matrices = (
            [cold, *warm[:2], recovery],
            [cold, *warm, recovery, dict(recovery)],
            [cold, *warm, {**recovery, "cache_hit": True}],
            [cold, *warm, {**recovery, "role": "unknown"}],
        )

        for matrix in malformed_matrices:
            with self.subTest(matrix=matrix):
                with self.assertRaisesRegex(RuntimeError, "sample matrix"):
                    compare_results(matrix)

    def test_compare_accepts_more_than_three_warm_samples(self) -> None:
        cold, warm, recovery = self._samples()

        verdict = compare_results([cold, *warm, dict(warm[0]), recovery])

        self.assertEqual(verdict["decision"], "accept")
        self.assertEqual(len(verdict["warm_prep_seconds"]), 4)

    def test_compare_rejects_nonpositive_cold_preparation(self) -> None:
        cold, warm, recovery = self._samples()
        cold["restore_seconds"] = 0.0
        cold["conan_install_seconds"] = 0.0

        with self.assertRaisesRegex(RuntimeError, "positive"):
            compare_results([cold, *warm, recovery])

    def test_compare_marks_single_warm_over_sixty_for_investigation(self) -> None:
        cold, warm, recovery = self._samples()
        warm[2]["restore_seconds"] = 41.0
        warm[2]["conan_install_seconds"] = 20.0

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "investigate")
        self.assertIn("60-second", " ".join(verdict["reasons"]))

    def test_compare_marks_warm_median_over_forty_five_for_investigation(self) -> None:
        cold, warm, recovery = self._samples()
        for sample in warm:
            sample["restore_seconds"] = 20.0
            sample["conan_install_seconds"] = 26.0

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "investigate")
        self.assertIn("45-second", " ".join(verdict["reasons"]))

    def test_compare_rejects_improvement_below_seventy_percent(self) -> None:
        cold, warm, recovery = self._samples()
        for sample in warm:
            sample["restore_seconds"] = 10.0
            sample["conan_install_seconds"] = 51.0

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "reject")
        self.assertLess(verdict["improvement_percent"], 70.0)
        self.assertIn("below 70%", " ".join(verdict["reasons"]))

    def test_compare_investigates_cache_over_one_gib(self) -> None:
        cold, warm, recovery = self._samples()
        recovery["cache_bytes"] = GIB + 1

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "investigate")
        self.assertEqual(verdict["largest_cache_bytes"], GIB + 1)
        self.assertIn("1 GiB", " ".join(verdict["reasons"]))

    def test_compare_rejects_cache_over_two_gib(self) -> None:
        cold, warm, recovery = self._samples()
        recovery["cache_bytes"] = 2 * GIB + 1

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "reject")
        self.assertIn("2 GiB", " ".join(verdict["reasons"]))

    def test_recovery_timing_does_not_affect_acceleration_decision(self) -> None:
        cold, warm, recovery = self._samples()
        recovery["restore_seconds"] = 100_000.0
        recovery["conan_install_seconds"] = 100_000.0

        verdict = compare_results([cold, *warm, recovery])

        self.assertEqual(verdict["decision"], "accept")
        self.assertEqual(verdict["improvement_percent"], 87.5)

    def test_collect_cli_writes_pretty_json_with_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            output = root / "collected.json"

            self._run_cli(
                "collect",
                "--cache-dir",
                str(cache),
                "--graph-file",
                str(graph),
                "--build-log",
                str(log),
                "--build-total-seconds",
                "20",
                "--output",
                str(output),
            )

            rendered = output.read_text(encoding="utf-8")
            self.assertTrue(rendered.endswith("\n"))
            self.assertIn("\n  \"cache_bytes\"", rendered)
            self.assertEqual(json.loads(rendered)["package_count"], 1)

    def test_report_cli_contains_metadata_and_p95_caveat_without_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collected = root / "collected.json"
            collected.write_text(
                json.dumps(
                    {
                        "cache_bytes": 11,
                        "cache_files": 2,
                        "conan_install_seconds": 12.5,
                        "graph_digest": "a" * 64,
                        "package_count": 1,
                        "project_build_seconds": 7.5,
                        "source_builds": [],
                        "dependency_refs": ["sentinel-secret-ref/1.0"],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "result.json"
            summary = root / "summary.md"

            self._run_cli(
                "report",
                "--collected",
                str(collected),
                "--output",
                str(output),
                "--summary",
                str(summary),
                "--role",
                "baseline",
                "--cache-hit",
                "true",
                "--restore-seconds",
                "3.25",
                "--save-seconds",
                "4.5",
                "--job-total-seconds",
                "30",
                "--generation",
                "v1",
                "--fingerprint",
                "fingerprint-123",
                "--run-id",
                "456",
                "--run-attempt",
                "2",
                "--sha",
                "deadbeef",
            )

            result_text = output.read_text(encoding="utf-8")
            result = json.loads(result_text)
            summary_text = summary.read_text(encoding="utf-8")
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["role"], "baseline")
            self.assertIs(result["cache_hit"], True)
            self.assertEqual(result["generation"], "v1")
            self.assertEqual(result["fingerprint"], "fingerprint-123")
            self.assertEqual(result["run_id"], "456")
            self.assertEqual(result["run_attempt"], "2")
            self.assertEqual(result["sha"], "deadbeef")
            self.assertTrue(result_text.endswith("\n"))
            for expected in (
                "baseline",
                "fingerprint-123",
                "deadbeef",
                "Cache restore",
                "Conan install",
                "Project build",
                "Cache save",
                "Total job",
                "Cache size",
                "Cache files",
                "Packages",
                "Graph digest",
                "directional evidence only",
                "P95",
            ):
                self.assertIn(expected, summary_text)
            self.assertNotIn("sentinel-secret-ref", result_text)
            self.assertNotIn("sentinel-secret-ref", summary_text)

    def test_compare_cli_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cold, warm, recovery = self._samples()
            samples = [cold, *warm, recovery]
            paths = []
            for index, sample in enumerate(samples):
                path = root / f"sample-{index}.json"
                path.write_text(json.dumps(sample), encoding="utf-8")
                paths.append(path)
            output = root / "verdict.json"

            self._run_cli(
                "compare", *(str(path) for path in paths), "--output", str(output)
            )

            rendered = output.read_text(encoding="utf-8")
            self.assertEqual(json.loads(rendered)["decision"], "accept")
            self.assertTrue(rendered.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
