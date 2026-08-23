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
TIMING_PATTERN = re.compile(
    r"^Conan install elapsed: ([0-9]+(?:\.[0-9]+)?)s$", re.MULTILINE
)


def _regular_cache_files(cache_dir: Path) -> list[Path]:
    """Return validated regular cache files without following symlinks."""
    if cache_dir.is_symlink():
        raise RuntimeError("download cache directory is a symlink")
    if not cache_dir.is_dir():
        raise RuntimeError(f"download cache is not a directory: {cache_dir}")

    files: list[Path] = []
    pending = [cache_dir]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path.is_symlink():
                raise RuntimeError(f"download cache contains symlink: {path}")
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                if path.name.casefold() in FORBIDDEN_NAMES:
                    raise RuntimeError(
                        f"download cache contains forbidden file: {path.name}"
                    )
                files.append(path)

    if not files:
        raise RuntimeError("download cache contains no regular files")
    return files


def _graph_identity(graph_file: Path) -> tuple[str, int]:
    """Reduce a Conan graph to a stable package identity digest and count."""
    try:
        payload = json.loads(graph_file.read_text(encoding="utf-8"))
        nodes = payload["graph"]["nodes"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Conan graph JSON does not contain graph.nodes") from error
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

    packages.sort(
        key=lambda package: json.dumps(
            package, sort_keys=True, separators=(",", ":")
        )
    )
    canonical = json.dumps(packages, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest, len(packages)


def _conan_install_seconds(build_log: Path) -> float:
    """Extract the single exact Conan install timing line from a build log."""
    matches = TIMING_PATTERN.findall(build_log.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise RuntimeError("build log does not contain exactly one Conan install timing line")
    return float(matches[0])


def collect(
    cache_dir: Path,
    graph_file: Path,
    build_log: Path,
    build_total_seconds: float,
) -> dict[str, Any]:
    """Validate one sample and return credential-free cache/build measurements."""
    files = _regular_cache_files(cache_dir)
    graph_digest, package_count = _graph_identity(graph_file)
    conan_seconds = _conan_install_seconds(build_log)
    return {
        "cache_bytes": sum(path.stat().st_size for path in files),
        "cache_files": len(files),
        "conan_install_seconds": conan_seconds,
        "graph_digest": graph_digest,
        "package_count": package_count,
        "project_build_seconds": max(0.0, build_total_seconds - conan_seconds),
        "source_builds": [],
    }


def _finite_number(result: Mapping[str, Any], field: str) -> float:
    """Read one finite numeric result field or reject the sample."""
    value = result.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Spike sample has invalid {field}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise RuntimeError(f"Spike sample has invalid {field}")
    return numeric


def _validate_result(result: Any) -> Mapping[str, Any]:
    """Validate fields used to compare a single result."""
    if not isinstance(result, Mapping):
        raise RuntimeError("malformed Spike sample matrix: result is not an object")
    if result.get("role") not in ("baseline", "recovery"):
        raise RuntimeError("malformed Spike sample matrix: unknown role")
    if type(result.get("cache_hit")) is not bool:
        raise RuntimeError("malformed Spike sample matrix: cache_hit must be boolean")
    if not isinstance(result.get("graph_digest"), str) or not result["graph_digest"]:
        raise RuntimeError("Spike sample has invalid graph digest")
    if "source_builds" not in result or not isinstance(result["source_builds"], list):
        raise RuntimeError("Spike sample has invalid source_builds")

    restore = _finite_number(result, "restore_seconds")
    install = _finite_number(result, "conan_install_seconds")
    cache_bytes = result.get("cache_bytes")
    if restore < 0.0 or install < 0.0:
        raise RuntimeError("Spike sample timings must be nonnegative")
    if isinstance(cache_bytes, bool) or not isinstance(cache_bytes, int) or cache_bytes < 0:
        raise RuntimeError("Spike sample has invalid cache_bytes")
    return result


def compare_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate Cold, Warm, and recovery results against Spike thresholds."""
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
        or len(warm) < 3
        or len(recovery) != 1
        or classified_count != len(samples)
    ):
        raise RuntimeError(
            "malformed Spike sample matrix: expected one Cold, at least three Warm, "
            "and one recovery miss"
        )

    if len({result["graph_digest"] for result in samples}) != 1:
        raise RuntimeError("dependency graph digest differs across Spike samples")
    if any(result["source_builds"] for result in samples):
        raise RuntimeError("source builds occurred in a Spike sample")

    cold_prep = _finite_number(cold[0], "restore_seconds") + _finite_number(
        cold[0], "conan_install_seconds"
    )
    if cold_prep <= 0.0:
        raise RuntimeError("Cold dependency preparation must be positive")
    warm_preps = [
        _finite_number(result, "restore_seconds")
        + _finite_number(result, "conan_install_seconds")
        for result in warm
    ]
    warm_median = statistics.median(warm_preps)
    warm_max = max(warm_preps)
    improvement = 100.0 * (1.0 - warm_median / cold_prep)
    largest_cache = max(int(result["cache_bytes"]) for result in samples)

    reject_reasons: list[str] = []
    investigate_reasons: list[str] = []
    if improvement < 70.0:
        reject_reasons.append("warm median improvement is below 70%")
    if largest_cache > 2 * GIB:
        reject_reasons.append("download cache exceeds 2 GiB")
    elif largest_cache > GIB:
        investigate_reasons.append("download cache exceeds the preferred 1 GiB")
    if warm_median > 45.0:
        investigate_reasons.append(
            "warm median exceeds the preferred 45-second budget"
        )
    if warm_max > 60.0:
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
        "improvement_percent": round(improvement, 1),
        "cold_prep_seconds": round(cold_prep, 3),
        "warm_prep_seconds": [round(value, 3) for value in warm_preps],
        "warm_median_seconds": round(warm_median, 3),
        "warm_max_seconds": round(warm_max, 3),
        "largest_cache_bytes": largest_cache,
        "graph_digest": str(samples[0]["graph_digest"]),
        "reasons": reasons,
    }


def _safe_collected_result(path: Path) -> dict[str, Any]:
    """Load only collector fields approved for publication."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("collected result must be a JSON object")
    missing = [field for field in COLLECTED_FIELDS if field not in payload]
    if missing:
        raise RuntimeError(f"collected result is missing fields: {', '.join(missing)}")
    result = {field: payload[field] for field in COLLECTED_FIELDS}
    if result["source_builds"] != []:
        raise RuntimeError("collected result contains source builds")
    return result


def _write_json(payload: Mapping[str, Any], destination: Path) -> None:
    """Write deterministic pretty JSON with a trailing newline."""
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")


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
    collect_parser.add_argument("--build-total-seconds", type=float, required=True)
    collect_parser.add_argument("--output", type=Path, required=True)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--collected", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    report_parser.add_argument("--summary", type=Path, required=True)
    report_parser.add_argument(
        "--role", choices=("baseline", "recovery"), required=True
    )
    report_parser.add_argument(
        "--cache-hit", choices=("true", "false"), required=True
    )
    report_parser.add_argument("--restore-seconds", type=float, required=True)
    report_parser.add_argument("--save-seconds", type=float, required=True)
    report_parser.add_argument("--job-total-seconds", type=float, required=True)
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
            args.build_total_seconds,
        )
        _write_json(result, args.output)
        return

    if args.command == "report":
        result = _safe_collected_result(args.collected)
        result.update(
            {
                "schema_version": 1,
                "role": args.role,
                "cache_hit": args.cache_hit == "true",
                "restore_seconds": args.restore_seconds,
                "save_seconds": args.save_seconds,
                "job_total_seconds": args.job_total_seconds,
                "generation": args.generation,
                "fingerprint": args.fingerprint,
                "run_id": args.run_id,
                "run_attempt": args.run_attempt,
                "sha": args.sha,
            }
        )
        _write_json(result, args.output)
        write_summary(result, args.summary)
        return

    results = [json.loads(path.read_text(encoding="utf-8")) for path in args.results]
    _write_json(compare_results(results), args.output)


if __name__ == "__main__":
    main()
