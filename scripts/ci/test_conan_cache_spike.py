"""Tests for credential-free Conan download-cache Spike evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.ci import conan_cache_spike as spike
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

    def _collected_payload(self, **updates: Any) -> dict[str, Any]:
        payload = {
            "cache_bytes": 11,
            "cache_files": 2,
            "conan_install_seconds": 12.5,
            "graph_digest": "a" * 64,
            "package_count": 1,
            "project_build_seconds": 7.5,
            "source_builds": [],
        }
        payload.update(updates)
        return payload

    def _report_arguments(
        self,
        root: Path,
        *,
        payload: dict[str, Any] | None = None,
        role: str = "baseline",
        cache_hit: str = "true",
        metadata: dict[str, str] | None = None,
        timings: dict[str, str] | None = None,
        output: Path | None = None,
        summary: Path | None = None,
    ) -> list[str]:
        collected = root / "collected.json"
        collected.write_text(
            json.dumps(self._collected_payload() if payload is None else payload),
            encoding="utf-8",
        )
        metadata_values = {
            "generation": "v1",
            "fingerprint": "a" * 64,
            "run-id": "456",
            "run-attempt": "2",
            "sha": "deadbeef",
        }
        metadata_values.update(metadata or {})
        timing_values = {
            "restore-seconds": "3.25",
            "save-seconds": "4.5",
            "job-total-seconds": "30",
        }
        timing_values.update(timings or {})
        arguments = [
            "report",
            "--collected",
            str(collected),
            "--output",
            str(root / "result.json" if output is None else output),
            "--summary",
            str(root / "summary.md" if summary is None else summary),
            "--role",
            role,
            "--cache-hit",
            cache_hit,
        ]
        for name, value in (*timing_values.items(), *metadata_values.items()):
            arguments.append(f"--{name}={value}")
        return arguments

    def _run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "scripts.ci.conan_cache_spike", *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def _threshold_verdict(
        self, warm_preps: tuple[float, float, float], *, cold_prep: float
    ) -> dict[str, Any]:
        cold, warm, recovery = self._samples()
        cold["restore_seconds"] = 0.0
        cold["conan_install_seconds"] = cold_prep
        for sample, prep in zip(warm, warm_preps):
            sample["restore_seconds"] = 0.0
            sample["conan_install_seconds"] = prep
        return compare_results([cold, *warm, recovery])

    def test_collect_emits_stable_safe_identity_and_timing_math(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)

            payload = json.loads(graph.read_text(encoding="utf-8"))
            payload["graph"]["nodes"]["2"] = {
                "ref": "openssl/3.3.2#second-recipe",
                "rrev": "second-recipe",
                "package_id": "second-package-id",
                "prev": "second-package-revision",
                "context": "host",
                "binary": "Cache",
            }
            graph.write_text(json.dumps(payload), encoding="utf-8")
            first = collect(cache, graph, log, build_total_seconds=20.0)
            payload["graph"]["nodes"] = {
                "0": payload["graph"]["nodes"]["0"],
                "2": payload["graph"]["nodes"]["2"],
                "1": payload["graph"]["nodes"]["1"],
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
            self.assertEqual(first["package_count"], 2)
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

    def test_collect_rejects_invalid_build_total_timings(self) -> None:
        invalid_values = (-1.0, float("nan"), float("inf"), float("-inf"), True)
        for value in invalid_values:
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    cache, graph, log = self._collection_inputs(root)

                    with self.assertRaisesRegex(RuntimeError, "timing"):
                        collect(cache, graph, log, build_total_seconds=value)

    def test_collect_rejects_invalid_conan_install_timings(self) -> None:
        invalid_values = ("-1", "NaN", "Infinity", "9" * 400)
        for value in invalid_values:
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    cache, graph, log = self._collection_inputs(root)
                    log.write_text(
                        f"Conan install elapsed: {value}s\n", encoding="utf-8"
                    )

                    with self.assertRaisesRegex(RuntimeError, "timing"):
                        collect(cache, graph, log, build_total_seconds=20.0)

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

    def test_cache_validation_errors_do_not_expose_paths_or_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "graph.json"
            self._graph(graph)
            log = root / "build.log"
            log.write_text("Conan install elapsed: 1s\n", encoding="utf-8")
            sentinel = "sentinel-private-cache-path"

            invalid_paths = []
            missing = root / sentinel
            invalid_paths.append(missing)
            symlink_cache = root / f"{sentinel}-symlink"
            target = root / "target"
            target.mkdir()
            (target / "archive").write_bytes(b"archive")
            symlink_cache.symlink_to(target, target_is_directory=True)
            invalid_paths.append(symlink_cache)
            forbidden_cache = root / "forbidden"
            forbidden_cache.mkdir()
            (forbidden_cache / "credentials.json").write_text(
                "secret", encoding="utf-8"
            )
            invalid_paths.append(forbidden_cache)

            for cache in invalid_paths:
                with self.subTest(cache=cache.name):
                    with self.assertRaises(RuntimeError) as context:
                        collect(cache, graph, log, build_total_seconds=2.0)
                    message = str(context.exception)
                    self.assertNotIn(sentinel, message)
                    self.assertNotIn("credentials.json", message)

    def test_missing_graph_and_log_errors_do_not_expose_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            sentinel = "sentinel-private-input-path"
            missing_graph = root / f"{sentinel}-graph.json"
            missing_log = root / f"{sentinel}-build.log"

            for graph_path, log_path in (
                (missing_graph, log),
                (graph, missing_log),
            ):
                with self.subTest(graph=graph_path.name, log=log_path.name):
                    with self.assertRaises(RuntimeError) as context:
                        collect(cache, graph_path, log_path, build_total_seconds=20.0)
                    self.assertNotIn(sentinel, str(context.exception))

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

    def test_collect_rejects_nonfinite_graph_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, graph, log = self._collection_inputs(root)
            payload = json.loads(graph.read_text(encoding="utf-8"))
            payload["graph"]["nodes"]["1"]["package_id"] = float("nan")
            graph.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "graph"):
                collect(cache, graph, log, build_total_seconds=20.0)

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

    def test_compare_rejects_invalid_individual_timings(self) -> None:
        invalid_values = (-1.0, float("nan"), float("inf"), float("-inf"), True)
        for field in ("restore_seconds", "conan_install_seconds"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    cold, warm, recovery = self._samples()
                    warm[0][field] = value

                    with self.assertRaisesRegex(RuntimeError, "timing"):
                        compare_results([cold, *warm, recovery])

    def test_compare_rejects_nonfinite_aggregate_timings(self) -> None:
        for sample_name in ("cold", "recovery"):
            with self.subTest(sample=sample_name):
                cold, warm, recovery = self._samples()
                sample = cold if sample_name == "cold" else recovery
                sample["restore_seconds"] = 1e308
                sample["conan_install_seconds"] = 1e308

                with self.assertRaisesRegex(RuntimeError, "timing"):
                    compare_results([cold, *warm, recovery])

    def test_compare_rejects_non_hex_graph_digest_without_exposing_it(self) -> None:
        cold, warm, recovery = self._samples()
        sentinel = "sentinel-private-dependency/1.0#revision"
        for sample in (cold, *warm, recovery):
            sample["graph_digest"] = sentinel

        with self.assertRaises(RuntimeError) as context:
            compare_results([cold, *warm, recovery])

        self.assertNotIn(sentinel, str(context.exception))

    def test_compare_cli_input_error_does_not_expose_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = "sentinel-private-result-path"
            missing = root / f"{sentinel}.json"

            with self.assertRaises(RuntimeError) as context:
                spike.main(
                    ["compare", str(missing), "--output", str(root / "verdict.json")]
                )

            self.assertNotIn(sentinel, str(context.exception))

    def test_collected_schema_rejects_malformed_allowlisted_values(self) -> None:
        invalid_cases: list[tuple[str, Any]] = []
        for field in ("cache_bytes", "cache_files", "package_count"):
            invalid_cases.extend(
                (field, value) for value in (-1, True, 1.5, "1")
            )
        for field in ("conan_install_seconds", "project_build_seconds"):
            invalid_cases.extend(
                (field, value)
                for value in (-1.0, True, float("nan"), float("inf"), "1")
            )
        invalid_cases.extend(
            (
                ("graph_digest", "a" * 63),
                ("graph_digest", "a" * 65),
                ("graph_digest", "g" * 64),
                ("graph_digest", 123),
                ("source_builds", ["sentinel-private-dependency/1.0"]),
                ("source_builds", {}),
                ("source_builds", None),
            )
        )

        for field, value in invalid_cases:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "collected.json"
                    path.write_text(
                        json.dumps(self._collected_payload(**{field: value})),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(RuntimeError, "collected") as context:
                        spike._safe_collected_result(path)
                    self.assertNotIn("sentinel-private-dependency", str(context.exception))

    def test_collected_schema_rejects_invalid_text_encoding_generically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentinel-private-collected.json"
            path.write_bytes(b"\xff")

            with self.assertRaisesRegex(RuntimeError, "collected") as context:
                spike._safe_collected_result(path)

            self.assertNotIn("sentinel-private-collected", str(context.exception))

    def test_report_rejects_invalid_timing_arguments(self) -> None:
        invalid_values = ("-1", "nan", "inf", "-inf")
        for field in (
            "restore-seconds",
            "save-seconds",
            "job-total-seconds",
        ):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        arguments = self._report_arguments(
                            root, timings={field: value}
                        )
                        with self.assertRaisesRegex(RuntimeError, "timing"):
                            spike.main(arguments)
                        self.assertFalse((root / "result.json").exists())
                        self.assertFalse((root / "summary.md").exists())

    def test_report_accepts_safe_single_line_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spike.main(self._report_arguments(root))

            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["generation"], "v1")
            self.assertEqual(result["fingerprint"], "a" * 64)
            self.assertEqual(result["run_id"], "456")
            self.assertEqual(result["run_attempt"], "2")
            self.assertEqual(result["sha"], "deadbeef")

    def test_report_rejects_unsafe_metadata_tokens(self) -> None:
        unsafe_cases = (
            ("generation", ""),
            ("generation", "line\nbreak"),
            ("generation", "bad|table"),
            ("fingerprint", "`code`"),
            ("run-id", "../secret"),
            ("run-attempt", "pkg/1.0#revision"),
            ("sha", "bad\\path"),
            ("sha", "control\x01character"),
        )
        for field, value in unsafe_cases:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    arguments = self._report_arguments(
                        root, metadata={field: value}
                    )
                    with self.assertRaisesRegex(RuntimeError, "metadata") as context:
                        spike.main(arguments)
                    if value:
                        self.assertNotIn(value, str(context.exception))
                    self.assertFalse((root / "result.json").exists())
                    self.assertFalse((root / "summary.md").exists())

    def test_report_rejects_recovery_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments = self._report_arguments(
                root, role="recovery", cache_hit="true"
            )

            with self.assertRaisesRegex(RuntimeError, "role"):
                spike.main(arguments)
            self.assertFalse((root / "result.json").exists())
            self.assertFalse((root / "summary.md").exists())

    def test_report_rejects_output_summary_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            output = root / "evidence.json"
            aliases = (output, nested / ".." / "evidence.json")

            for summary in aliases:
                with self.subTest(summary=summary):
                    arguments = self._report_arguments(
                        root, output=output, summary=summary
                    )
                    with self.assertRaisesRegex(RuntimeError, "destinations"):
                        spike.main(arguments)
                    self.assertFalse(output.exists())

    def test_json_writer_rejects_nonfinite_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with self.assertRaises(ValueError):
                spike._write_json({"invalid": float("nan")}, output)
            self.assertFalse(output.exists())

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

    def test_improvement_boundary_uses_published_one_decimal_value(self) -> None:
        cases = (
            ("just below", 30.06, 69.9, "reject"),
            ("exact", 30.04, 70.0, "accept"),
            ("just above", 29.94, 70.1, "accept"),
        )
        for label, warm_prep, published, decision in cases:
            with self.subTest(label=label):
                verdict = self._threshold_verdict(
                    (warm_prep, warm_prep, warm_prep), cold_prep=100.0
                )
                self.assertEqual(verdict["improvement_percent"], published)
                self.assertEqual(verdict["decision"], decision)

    def test_warm_median_boundary_uses_published_three_decimal_value(self) -> None:
        cases = (
            ("just below", 44.999, 44.999, "accept"),
            ("exact", 45.0004, 45.0, "accept"),
            ("just above", 45.0006, 45.001, "investigate"),
        )
        for label, warm_prep, published, decision in cases:
            with self.subTest(label=label):
                verdict = self._threshold_verdict(
                    (warm_prep, warm_prep, warm_prep), cold_prep=200.0
                )
                self.assertEqual(verdict["warm_median_seconds"], published)
                self.assertEqual(verdict["decision"], decision)

    def test_warm_max_boundary_uses_published_three_decimal_value(self) -> None:
        cases = (
            ("just below", 59.999, 59.999, "accept"),
            ("exact", 60.0004, 60.0, "accept"),
            ("just above", 60.0006, 60.001, "investigate"),
        )
        for label, warm_max, published, decision in cases:
            with self.subTest(label=label):
                verdict = self._threshold_verdict(
                    (20.0, 25.0, warm_max), cold_prep=200.0
                )
                self.assertEqual(verdict["warm_max_seconds"], published)
                self.assertEqual(verdict["decision"], decision)

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
                "a" * 64,
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
            self.assertEqual(result["fingerprint"], "a" * 64)
            self.assertEqual(result["run_id"], "456")
            self.assertEqual(result["run_attempt"], "2")
            self.assertEqual(result["sha"], "deadbeef")
            self.assertTrue(result_text.endswith("\n"))
            for expected in (
                "baseline",
                "a" * 64,
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
