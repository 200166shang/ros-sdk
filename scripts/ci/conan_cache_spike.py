"""Collect and compare credential-free Conan download-cache Spike results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence


FORBIDDEN_NAMES = {
    "credentials.json",
    "global.conf",
    "remotes.json",
    "settings.yml",
    "source_credentials.json",
}
GIB = 1024**3
GRAPH_FIELDS = ("ref", "rrev", "package_id", "prev", "context")
COLLECTED_FIELDS = (
    "cache_bytes",
    "cache_files",
    "conan_install_seconds",
    "graph_digest",
    "package_count",
    "project_build_seconds",
    "source_builds",
)
RESULT_FIELDS = frozenset(
    (
        *COLLECTED_FIELDS,
        "schema_version",
        "role",
        "cache_hit",
        "restore_seconds",
        "save_seconds",
        "job_total_seconds",
        "generation",
        "fingerprint",
        "run_id",
        "run_attempt",
        "sha",
    )
)
RESULT_TIMING_FIELDS = (
    "restore_seconds",
    "conan_install_seconds",
    "project_build_seconds",
    "save_seconds",
    "job_total_seconds",
)
RESULT_COUNT_FIELDS = ("cache_bytes", "cache_files", "package_count")
# Four independently rounded component timings plus the rounded job total can
# differ by at most 2.5 ms. Use 3 ms to cover that publication error.
TIMING_ROUNDING_TOLERANCE_SECONDS = 0.003
TIMING_PATTERN = re.compile(
    r"^Conan install elapsed: ([0-9]+(?:\.[0-9]+)?)s$", re.MULTILINE
)
GRAPH_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
SAFE_METADATA_PATTERN = re.compile(r"[A-Za-z0-9]+")
POSITIVE_DECIMAL_PATTERN = re.compile(r"[1-9][0-9]*")
SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")


def _regular_cache_files(cache_dir: Path) -> list[Path]:
    """Return validated regular cache files without following symlinks."""
    try:
        if cache_dir.is_symlink():
            raise RuntimeError("download cache contains a symlink")
        if not cache_dir.is_dir():
            raise RuntimeError("download cache is not a directory")

        files: list[Path] = []
        pending = [cache_dir]
        while pending:
            directory = pending.pop()
            for path in directory.iterdir():
                if path.is_symlink():
                    raise RuntimeError("download cache contains a symlink")
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    if path.name.casefold() in FORBIDDEN_NAMES:
                        raise RuntimeError(
                            "download cache contains forbidden configuration"
                        )
                    files.append(path)
    except OSError:
        raise RuntimeError("download cache could not be validated") from None

    if not files:
        raise RuntimeError("download cache contains no regular files")
    return files


def _graph_identity(graph_file: Path) -> tuple[str, int]:
    """Reduce a Conan graph to a stable package identity digest and count."""
    try:
        payload = json.loads(graph_file.read_text(encoding="utf-8"))
        nodes = payload["graph"]["nodes"]
    except (KeyError, OSError, TypeError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("Conan graph JSON is invalid") from None
    if not isinstance(nodes, Mapping):
        raise RuntimeError("Conan graph JSON graph.nodes must be an object")

    packages: list[dict[str, Any]] = []
    source_build_count = 0
    for node in nodes.values():
        if not isinstance(node, Mapping):
            raise RuntimeError("Conan graph JSON contains an invalid dependency node")
        ref = node.get("ref")
        if not ref or ref == "conanfile":
            continue
        identity = {field: node.get(field) for field in GRAPH_FIELDS}
        packages.append(identity)
        if str(node.get("binary", "")).casefold() == "build":
            source_build_count += 1

    if source_build_count:
        noun = "dependency" if source_build_count == 1 else "dependencies"
        raise RuntimeError(
            f"Conan attempted source builds for {source_build_count} {noun}"
        )

    try:
        packages.sort(
            key=lambda package: json.dumps(
                package, allow_nan=False, sort_keys=True, separators=(",", ":")
            )
        )
        canonical = json.dumps(
            packages, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        raise RuntimeError("Conan graph JSON is invalid") from None
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest, len(packages)


def _conan_install_seconds(build_log: Path) -> float:
    """Extract the single exact Conan install timing line from a build log."""
    try:
        log_text = build_log.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise RuntimeError("build log timing evidence is invalid") from None
    matches = TIMING_PATTERN.findall(log_text)
    if len(matches) != 1:
        raise RuntimeError("build log does not contain exactly one Conan install timing line")
    return _nonnegative_finite_timing(float(matches[0]))


def _nonnegative_finite_timing(value: Any) -> float:
    """Return a finite nonnegative timing or reject the evidence."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError("Spike evidence contains an invalid timing")
    try:
        timing = float(value)
    except OverflowError:
        raise RuntimeError("Spike evidence contains an invalid timing") from None
    if not math.isfinite(timing) or timing < 0.0:
        raise RuntimeError("Spike evidence contains an invalid timing")
    return timing


def _nonnegative_integer(value: Any) -> int:
    """Return a nonnegative integer or reject the evidence."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("Spike evidence contains an invalid count")
    return value


def _safe_metadata_token(value: Any) -> str:
    """Return a Markdown-safe, single-line metadata token."""
    if not isinstance(value, str) or SAFE_METADATA_PATTERN.fullmatch(value) is None:
        raise RuntimeError("report metadata contains an invalid token")
    return value


def _fingerprint_token(value: Any) -> str:
    """Return an exact lowercase SHA-256 environment fingerprint."""
    if not isinstance(value, str) or GRAPH_DIGEST_PATTERN.fullmatch(value) is None:
        raise RuntimeError("report metadata contains an invalid token")
    return value


def _positive_decimal_token(value: Any) -> str:
    """Return a canonical positive decimal GitHub run identifier."""
    if not isinstance(value, str) or POSITIVE_DECIMAL_PATTERN.fullmatch(value) is None:
        raise RuntimeError("report metadata contains an invalid token")
    return value


def _sha1_token(value: Any) -> str:
    """Return a lowercase full-length GitHub commit SHA."""
    if not isinstance(value, str) or SHA1_PATTERN.fullmatch(value) is None:
        raise RuntimeError("report metadata contains an invalid token")
    return value


def _timing_argument(value: Any) -> float:
    """Parse an untrusted CLI timing without echoing its source text."""
    try:
        timing = float(value)
    except (TypeError, ValueError):
        raise RuntimeError("Spike evidence contains an invalid timing") from None
    return _nonnegative_finite_timing(timing)


def collect(
    cache_dir: Path,
    graph_file: Path,
    build_log: Path,
    build_total_seconds: float,
) -> dict[str, Any]:
    """Validate one sample and return credential-free cache/build measurements."""
    total_seconds = _nonnegative_finite_timing(build_total_seconds)
    files = _regular_cache_files(cache_dir)
    graph_digest, package_count = _graph_identity(graph_file)
    conan_seconds = _conan_install_seconds(build_log)
    if total_seconds < conan_seconds:
        raise RuntimeError("Spike evidence contains contradictory timing")
    return {
        "cache_bytes": sum(path.stat().st_size for path in files),
        "cache_files": len(files),
        "conan_install_seconds": conan_seconds,
        "graph_digest": graph_digest,
        "package_count": package_count,
        "project_build_seconds": total_seconds - conan_seconds,
        "source_builds": [],
    }


def _validate_result(result: Any) -> Mapping[str, Any]:
    """Validate the complete published schema for one Spike result."""
    if not isinstance(result, Mapping):
        raise RuntimeError("malformed Spike sample matrix: result schema is invalid")
    try:
        fields = frozenset(result)
    except TypeError:
        raise RuntimeError("malformed Spike sample matrix: result schema is invalid") from None
    if fields != RESULT_FIELDS:
        raise RuntimeError("malformed Spike sample matrix: result schema is invalid")
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise RuntimeError("malformed Spike sample matrix: result schema is invalid")
    if result.get("role") not in ("baseline", "recovery"):
        raise RuntimeError("malformed Spike sample matrix: result schema is invalid")
    if type(result.get("cache_hit")) is not bool:
        raise RuntimeError("malformed Spike sample matrix: result schema is invalid")
    if (
        not isinstance(result.get("graph_digest"), str)
        or GRAPH_DIGEST_PATTERN.fullmatch(result["graph_digest"]) is None
    ):
        raise RuntimeError(
            "malformed Spike sample matrix: result schema has invalid graph digest"
        )
    if "source_builds" not in result or not isinstance(result["source_builds"], list):
        raise RuntimeError(
            "malformed Spike sample matrix: result schema has invalid source_builds"
        )

    try:
        timings = {
            field: _nonnegative_finite_timing(result[field])
            for field in RESULT_TIMING_FIELDS
        }
        # Dependency preparation is the sixth timing used by the comparison.
        _nonnegative_finite_timing(
            timings["restore_seconds"] + timings["conan_install_seconds"]
        )
        accounted_job_seconds = _nonnegative_finite_timing(
            timings["restore_seconds"]
            + timings["conan_install_seconds"]
            + timings["project_build_seconds"]
            + timings["save_seconds"]
        )
    except RuntimeError:
        raise RuntimeError(
            "malformed Spike sample matrix: result schema has invalid timing"
        ) from None
    if (
        timings["job_total_seconds"] + TIMING_ROUNDING_TOLERANCE_SECONDS
        < accounted_job_seconds
        or (result["cache_hit"] and timings["save_seconds"] != 0.0)
    ):
        raise RuntimeError(
            "malformed Spike sample matrix: result evidence is inconsistent"
        )
    try:
        for field in RESULT_COUNT_FIELDS:
            _nonnegative_integer(result[field])
    except RuntimeError:
        raise RuntimeError(
            "malformed Spike sample matrix: result schema has invalid count"
        ) from None
    if (
        not isinstance(result["generation"], str)
        or SAFE_METADATA_PATTERN.fullmatch(result["generation"]) is None
        or not isinstance(result["fingerprint"], str)
        or GRAPH_DIGEST_PATTERN.fullmatch(result["fingerprint"]) is None
        or not isinstance(result["run_id"], str)
        or POSITIVE_DECIMAL_PATTERN.fullmatch(result["run_id"]) is None
        or not isinstance(result["run_attempt"], str)
        or POSITIVE_DECIMAL_PATTERN.fullmatch(result["run_attempt"]) is None
        or not isinstance(result["sha"], str)
        or SHA1_PATTERN.fullmatch(result["sha"]) is None
    ):
        raise RuntimeError(
            "malformed Spike sample matrix: result schema has invalid metadata"
        )
    return result


def compare_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate Cold, Warm, and recovery results against Spike thresholds."""
    if len(results) != 5:
        raise RuntimeError("malformed Spike five-sample matrix")
    samples = [_validate_result(result) for result in results]
    cold = [
        result
        for result in samples
        if result["role"] == "baseline" and not result["cache_hit"]
    ]
    warm = [
        result
        for result in samples
        if result["role"] == "baseline" and result["cache_hit"]
    ]
    recovery = [
        result
        for result in samples
        if result["role"] == "recovery" and not result["cache_hit"]
    ]
    classified_count = len(cold) + len(warm) + len(recovery)
    if (
        len(cold) != 1
        or len(warm) != 3
        or len(recovery) != 1
        or classified_count != len(samples)
    ):
        raise RuntimeError(
            "malformed Spike sample matrix: expected one Cold, three Warm, and one "
            "recovery miss"
        )

    if len({result["graph_digest"] for result in samples}) != 1:
        raise RuntimeError("dependency graph digest differs across Spike samples")
    if len({result["package_count"] for result in samples}) != 1:
        raise RuntimeError("Spike sample evidence is inconsistent")
    if any(result["source_builds"] for result in samples):
        raise RuntimeError("source builds occurred in a Spike sample")

    baseline = [*cold, *warm]
    baseline_identity = cold[0]
    baseline_attempts = [int(result["run_attempt"]) for result in baseline]
    cold_attempt = int(cold[0]["run_attempt"])
    warm_attempts = [int(result["run_attempt"]) for result in warm]
    sample_keys = {(result["run_id"], result["run_attempt"]) for result in samples}
    recovery_sample = recovery[0]
    if (
        any(result["generation"] != "v1" for result in baseline)
        or any(
            result["fingerprint"] != baseline_identity["fingerprint"]
            for result in baseline
        )
        or any(result["run_id"] != baseline_identity["run_id"] for result in baseline)
        or any(result["sha"] != baseline_identity["sha"] for result in baseline)
        or len(set(baseline_attempts)) != 4
        or any(attempt <= cold_attempt for attempt in warm_attempts)
        or recovery_sample["generation"] != "v2"
        or recovery_sample["fingerprint"] != baseline_identity["fingerprint"]
        or recovery_sample["run_id"] == baseline_identity["run_id"]
        or recovery_sample["sha"] == baseline_identity["sha"]
        or len(sample_keys) != 5
    ):
        raise RuntimeError("Spike results are not a comparable five-sample sequence")

    warm.sort(key=lambda result: int(result["run_attempt"]))

    cold_prep = _nonnegative_finite_timing(
        _nonnegative_finite_timing(cold[0]["restore_seconds"])
        + _nonnegative_finite_timing(cold[0]["conan_install_seconds"])
    )
    cold_prep_published = round(cold_prep, 3)
    if cold_prep_published <= 0.0:
        raise RuntimeError("Cold dependency preparation must be positive")
    warm_preps_raw = [
        _nonnegative_finite_timing(
            _nonnegative_finite_timing(result["restore_seconds"])
            + _nonnegative_finite_timing(result["conan_install_seconds"])
        )
        for result in warm
    ]
    warm_preps_published = [round(value, 3) for value in warm_preps_raw]
    warm_median_published = round(statistics.median(warm_preps_published), 3)
    warm_max_published = round(max(warm_preps_published), 3)
    improvement_published = round(
        100.0 * (1.0 - warm_median_published / cold_prep_published), 1
    )
    if not math.isfinite(improvement_published):
        raise RuntimeError("Spike comparison produced an invalid timing metric")
    largest_cache = max(int(result["cache_bytes"]) for result in samples)

    reject_reasons: list[str] = []
    investigate_reasons: list[str] = []
    if improvement_published < 70.0:
        reject_reasons.append("warm median improvement is below 70%")
    if largest_cache > 2 * GIB:
        reject_reasons.append("download cache exceeds 2 GiB")
    elif largest_cache > GIB:
        investigate_reasons.append("download cache exceeds the preferred 1 GiB")
    if warm_median_published > 45.0:
        investigate_reasons.append(
            "warm median exceeds the preferred 45-second budget"
        )
    if warm_max_published > 60.0:
        investigate_reasons.append(
            "at least one Warm sample exceeds the 60-second observation line"
        )

    if reject_reasons:
        decision = "reject"
        reasons = [*reject_reasons, *investigate_reasons]
    elif investigate_reasons:
        decision = "investigate"
        reasons = investigate_reasons
    else:
        decision = "accept"
        reasons = ["warm acceleration and cache capacity meet Spike thresholds"]

    return {
        "decision": decision,
        "improvement_percent": improvement_published,
        "cold_prep_seconds": cold_prep_published,
        "warm_prep_seconds": warm_preps_published,
        "warm_median_seconds": warm_median_published,
        "warm_max_seconds": warm_max_published,
        "largest_cache_bytes": largest_cache,
        "graph_digest": str(samples[0]["graph_digest"]),
        "reasons": reasons,
    }


def _safe_collected_result(path: Path) -> dict[str, Any]:
    """Load only collector fields approved for publication."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("collected result has an invalid schema") from None
    if not isinstance(payload, Mapping):
        raise RuntimeError("collected result has an invalid schema")
    missing = [field for field in COLLECTED_FIELDS if field not in payload]
    if missing:
        raise RuntimeError("collected result has an invalid schema")
    try:
        cache_bytes = _nonnegative_integer(payload["cache_bytes"])
        cache_files = _nonnegative_integer(payload["cache_files"])
        package_count = _nonnegative_integer(payload["package_count"])
        conan_seconds = _nonnegative_finite_timing(
            payload["conan_install_seconds"]
        )
        project_seconds = _nonnegative_finite_timing(
            payload["project_build_seconds"]
        )
    except RuntimeError:
        raise RuntimeError("collected result has an invalid schema") from None
    graph_digest = payload["graph_digest"]
    if (
        not isinstance(graph_digest, str)
        or GRAPH_DIGEST_PATTERN.fullmatch(graph_digest) is None
        or payload["source_builds"] != []
    ):
        raise RuntimeError("collected result has an invalid schema")
    return {
        "cache_bytes": cache_bytes,
        "cache_files": cache_files,
        "conan_install_seconds": conan_seconds,
        "graph_digest": graph_digest,
        "package_count": package_count,
        "project_build_seconds": project_seconds,
        "source_builds": [],
    }


def _write_json(payload: Mapping[str, Any], destination: Path) -> None:
    """Write deterministic pretty JSON with a trailing newline."""
    rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
    try:
        destination.write_text(rendered, encoding="utf-8")
    except OSError:
        raise RuntimeError("result JSON could not be written") from None


def write_summary(result: Mapping[str, Any], destination: Path) -> None:
    """Write a compact credential-free GitHub Job Summary."""
    rows = [
        "## Conan download cache Spike",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Schema version | {result['schema_version']} |",
        f"| Role | `{result['role']}` |",
        f"| Cache hit | `{str(result['cache_hit']).lower()}` |",
        f"| Generation | `{result['generation']}` |",
        f"| Fingerprint | `{result['fingerprint']}` |",
        f"| Run ID | `{result['run_id']}` |",
        f"| Run attempt | `{result['run_attempt']}` |",
        f"| SHA | `{result['sha']}` |",
        f"| Cache restore | {result['restore_seconds']:.3f}s |",
        f"| Conan install | {result['conan_install_seconds']:.3f}s |",
        f"| Project build | {result['project_build_seconds']:.3f}s |",
        f"| Cache save | {result['save_seconds']:.3f}s |",
        f"| Total job | {result['job_total_seconds']:.3f}s |",
        f"| Cache size | {result['cache_bytes']} bytes |",
        f"| Cache files | {result['cache_files']} |",
        f"| Packages | {result['package_count']} |",
        f"| Source builds | {len(result['source_builds'])} |",
        f"| Graph digest | `{result['graph_digest']}` |",
        "",
        "Three Warm samples are directional evidence only; production P95 requires at "
        "least 20 comparable successful shadow runs.",
    ]
    try:
        destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    except OSError:
        raise RuntimeError("result summary could not be written") from None


def _parser() -> argparse.ArgumentParser:
    """Create the Conan cache Spike command-line parser."""
    parser = argparse.ArgumentParser(
        description="Collect and compare Conan download-cache Spike evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--cache-dir", type=Path, required=True)
    collect_parser.add_argument("--graph-file", type=Path, required=True)
    collect_parser.add_argument("--build-log", type=Path, required=True)
    collect_parser.add_argument("--build-total-seconds", required=True)
    collect_parser.add_argument("--output", type=Path, required=True)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--collected", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    report_parser.add_argument("--summary", type=Path, required=True)
    report_parser.add_argument("--role", required=True)
    report_parser.add_argument("--cache-hit", required=True)
    report_parser.add_argument("--restore-seconds", required=True)
    report_parser.add_argument("--save-seconds", required=True)
    report_parser.add_argument("--job-total-seconds", required=True)
    report_parser.add_argument("--generation", required=True)
    report_parser.add_argument("--fingerprint", required=True)
    report_parser.add_argument("--run-id", required=True)
    report_parser.add_argument("--run-attempt", required=True)
    report_parser.add_argument("--sha", required=True)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("results", nargs="+", type=Path)
    compare_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the collect, report, or compare command."""
    args = _parser().parse_args(argv)
    if args.command == "collect":
        result = collect(
            args.cache_dir,
            args.graph_file,
            args.build_log,
            _timing_argument(args.build_total_seconds),
        )
        _write_json(result, args.output)
        return

    if args.command == "report":
        if args.role not in ("baseline", "recovery") or args.cache_hit not in (
            "true",
            "false",
        ):
            raise RuntimeError("report role or cache-hit value is invalid")
        cache_hit = args.cache_hit == "true"
        if args.role == "recovery" and cache_hit:
            raise RuntimeError("report role and cache-hit combination is invalid")
        try:
            destinations_alias = args.output.resolve() == args.summary.resolve()
        except (OSError, RuntimeError):
            raise RuntimeError("report destinations are invalid") from None
        if destinations_alias:
            raise RuntimeError("report destinations must be distinct")
        result = _safe_collected_result(args.collected)
        restore_seconds = _timing_argument(args.restore_seconds)
        save_seconds = _timing_argument(args.save_seconds)
        job_total_seconds = _timing_argument(args.job_total_seconds)
        generation = _safe_metadata_token(args.generation)
        fingerprint = _fingerprint_token(args.fingerprint)
        run_id = _positive_decimal_token(args.run_id)
        run_attempt = _positive_decimal_token(args.run_attempt)
        sha = _sha1_token(args.sha)
        result.update(
            {
                "schema_version": 1,
                "role": args.role,
                "cache_hit": cache_hit,
                "restore_seconds": restore_seconds,
                "save_seconds": save_seconds,
                "job_total_seconds": job_total_seconds,
                "generation": generation,
                "fingerprint": fingerprint,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "sha": sha,
            }
        )
        _validate_result(result)
        _write_json(result, args.output)
        write_summary(result, args.summary)
        return

    results = []
    for path in args.results:
        try:
            results.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RuntimeError("Spike result JSON is invalid") from None
    _write_json(compare_results(results), args.output)


if __name__ == "__main__":
    main()
