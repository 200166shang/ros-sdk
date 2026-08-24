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

## Conan download-cache identity

`scripts/ci/cache_canary.py` owns the compatibility identity used by local development and GitHub
Actions. Both environments run the same command inside their active `ros2` image:

```bash
python3 -m scripts.ci cache-identity --generation v1
```

The environment fingerprint canonicalizes the effective ARM64 environment: Ubuntu and ROS
identity, GCC target/version, glibc, Conan version, effective host and build profile output,
Release/C++17/ARM64 Gate settings, declared Conan options, and the shared Docker base inputs. The
Docker input digest stops at the `FROM base AS ci` boundary and includes the shared entrypoint, so
changes to the later simulator-only `dev` stage do not change compatibility identity.

The locked dependency hash is separate and covers both `conan.lock` and `conanfile.txt`. The
resulting cache contract is:

```text
rosbridge-conan-download-<generation>-<architecture>-<environment-fingerprint>-<locked-hash>
```

Actions first requests the exact key. Its only restore prefix removes `<locked-hash>`, so prior
packages may be reused only under the same generation, architecture, and normalized environment.
Changing generation also changes the prefix and therefore forces a Cold/Recovery path.

## Trusted producer and read-only canary

`.github/workflows/conan-cache-producer.yml` is the only workflow introduced by the cache boundary
that has `actions: write` and a cache save step. It runs only from trusted `main` code (pushes that
change identity inputs, or an explicit dispatch), restores exact/compatible payload first, and saves
an immutable exact key only after the Server Gate, graph validation, project build, credential scan,
and size policy succeed.

`.github/workflows/conan-cache-canary.yml` is a dispatch-only, `actions: read` consumer. It has no
cache save step. The selected `cold`, `warm`, or `recovery` role must match the observed restoration:
Cold and Recovery require a miss; Warm requires an exact key. A new generation is used for the
Recovery control. Both workflows continue through the restricted SSH tunnel and the required Conan
remote even on an exact hit, so cached payload never becomes package authority.

`scripts/ci/conan_cache_tunnel.sh` keeps SSH keys and known-host material in a mode-0600 temporary
directory, exposes only a loopback endpoint, passes Conan credentials only to an ephemeral container,
and places `CONAN_HOME` on tmpfs. Only `.cache/conan-download` survives for Actions Cache; graph JSON,
Conan client configuration, raw output, and credentials are excluded.

## Canary evidence and capacity policy

Each successful producer/canary run uploads one seven-day JSON result containing cache identity and
restore kind, required-Server success, exact graph digest/package count, an empty source-build list,
restore/Conan/build/total timing, and before/after cache bytes, files, and payload digest. Exact Warm
runs fail if the download-cache payload changes, providing observable evidence that complete cached
payload was not fetched again.

Before publication, the cache scanner rejects symlinks, Conan/SSH credential configuration, and any
known credential bytes. An entry above 1 GiB emits a warning; an entry above 2 GiB is not saved.
Repository Actions cache usage at or above 80% of the free 10-GiB allowance emits a warning. These
capacity observations do not weaken strict Server or zero-source-build correctness.

## Migration boundary

The existing production commands keep their current behavior until a later migration ticket changes
workflow wiring. In particular, `detect-changes`, `prepare-image`, and `build-workspace` are not
delegated to this module by Issue #82. This lets canary workflows exercise the shared plan and Gate
before required PR checks adopt them. Issue #83 adds the producer and read-only canary but still does
not modify `.github/workflows/pr-checks.yml` or make the canary a required check.
