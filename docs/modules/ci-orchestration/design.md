# CI Orchestration Design

## Status and scope

The shared CI orchestration boundary is implemented in `scripts/ci/orchestration.py`. It owns
change classification, explainable execution plans, the strict ARM64 Conan dependency Gate,
bounded retry policy, terminal failure classes, and safe diagnostics.

GitHub Actions remains responsible for event and permission wiring, runner selection, credentials,
SSH tunnel setup, cache restore/save operations, and invoking the shared boundary. Issue #82 adds
the boundary but deliberately does not switch `.github/workflows/pr-checks.yml` to it.

## Inputs and outputs

`create_execution_plan()` accepts:

- an event type: pull request or push to `main`;
- the complete changed-file set;
- the observed dependency-cache state: hit, miss, or restore-service failure.

It returns a JSON-serializable plan containing:

- the selected execution class;
- every input that triggered environment validation, its category, and its reason;
- the Warm, Cold, or strict-Server-fallback dependency path;
- ordered phases and the steps in each phase;
- explicit image publication eligibility;
- a human-readable explanation.

Steps in the same phase may execute concurrently. Build remains a prerequisite for the checks
phase, where lint and test can run in parallel.

The CLI exposes the same contract without changing workflow state:

```bash
python3 -m scripts.ci plan \
  --event pull-request \
  --cache-state miss \
  --changed-file conan.lock
```

## Change classification

| Category | Inputs | PR behavior | Post-merge image publication |
|---|---|---|---|
| Docker environment | `Dockerfile`, `docker/**`, Compose service configuration | Candidate environment | Only Dockerfile and `docker/**` are image inputs |
| Conan dependencies | `conanfile.txt`, `conanfile.py`, `conan.lock` | Candidate environment | No |
| ROS/CMake dependencies | `package.xml`, `CMakeLists.txt`, `*.cmake` | Candidate environment | No |
| Profile/fingerprint | Conan profiles and compatibility fingerprint policy | Candidate environment | No |
| CI behavior | workflows, actions, CI helpers, required-check entry points | Candidate environment | No |
| Source only | known source, test, documentation, and non-CI script inputs | Reusable image | No |
| Ambiguous | input not covered by a known source-only rule | Candidate environment | No |

Classification fails conservatively: a new or unknown input enters the environment path and is
reported as an `ambiguous` trigger. A push to `main` receives image publication eligibility only
when an actual image input changed.

## Strict dependency Gate

`build_strict_conan_command()` always constructs a Conan install with all of these constraints:

- one required named remote selected with `--remote`;
- the repository lockfile selected with `--lockfile`;
- separate required host and build profiles;
- `arch=armv8` build and host settings, plus Release and C++17 host settings;
- `--build=never` with no fallback that can compile a missing package;
- an optional absolute `core.download:download_cache` path.

The Gate can be invoked after the workflow has established its restricted tunnel and configured
the named read-only Conan remote:

```bash
python3 -m scripts.ci dependency-gate \
  --remote rosbridge \
  --cache-state hit \
  --download-cache /workspace/.cache/conan-download
```

A cache hit remains a Warm optimization, not a second package authority. Conan still resolves the
locked graph against the required remote. A cache miss is a normal Cold path. A cache restore
service failure records the cache failure and proceeds only through this same strict Server path.

## Retry and terminal policy

| Failure | Terminal class | Automatic retry |
|---|---|---|
| Tunnel, connectivity, or download timeout | `tunnel-connectivity` | One additional attempt |
| Host-key or authentication | `host-auth` | No |
| Missing exact ARM64 package | `arm64-package-preparation` | No |
| Lockfile, profile, remote, or other configuration | `configuration` | No |
| Cache restore service | `cache-service` | No; continue through strict Server path |
| Build, lint, or test | `project` | No |

Each dependency attempt is capped at 420 seconds. With one bounded one-second backoff, the maximum
two-attempt Gate remains below the specification's fifteen-minute dependency-access limit.

## Diagnostic safety

Gate output is captured rather than streamed. Conclusions replace caller-provided secret values,
credential-bearing URL userinfo, password/token/authorization assignments, and Basic/Bearer values.
Published diagnostics are normalized and capped at 1200 characters. Commands contain a remote name,
profiles, settings, lockfile, and cache paths only; credentials are never command arguments.

The stable conclusion is intended for logs, job summaries, metrics, and tests. Raw dependency output
must not be uploaded as a success artifact or copied into a shared cache.

## Migration boundary

The existing production commands keep their current behavior until a later migration ticket changes
workflow wiring. In particular, `detect-changes`, `prepare-image`, and `build-workspace` are not
delegated to this module by Issue #82. This lets canary workflows exercise the shared plan and Gate
before required PR checks adopt them.
