"""Behavior tests for the trusted Conan download-cache canary boundary."""

from __future__ import annotations

import copy
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ci.cache_canary import (
    CanaryRequest,
    GIB,
    RestoreKind,
    SampleRole,
    build_cache_identity,
    classify_cache_restore,
    collect_environment_evidence,
    configure_required_remote,
    evaluate_cache_capacity,
    inspect_download_cache,
    read_graph_evidence,
    run_canary,
    shared_base_digest,
)
from scripts.ci.__main__ import main
from scripts.ci.orchestration import (
    CacheState,
    CommandResult,
    DependencyPath,
    FailureClass,
    GateConclusion,
)


class CacheIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = {
            "architecture": "aarch64",
            "os": {"id": "ubuntu", "version_id": "24.04"},
            "ros": {"distro": "jazzy"},
            "compiler": {"id": "gcc", "target": "aarch64-linux-gnu", "version": "13.3.0"},
            "libc": {"id": "glibc", "version": "2.39"},
            "conan": {"version": "2.31.2"},
            "host_profile": {
                "settings": {"arch": "armv8", "build_type": "Release"},
            },
            "build_profile": {
                "settings": {"arch": "armv8", "build_type": "Release"},
            },
            "build_settings": {
                "build_type": "Release",
                "compiler.cppstd": "17",
            },
            "options": {
                "grpc/*:codegen": "True",
                "grpc/*:cpp_plugin": "True",
                "grpc/*:shared": "False",
            },
            "shared_base": {"digest": "a" * 64},
        }

    def _identity(self, root: Path, evidence: dict | None = None, generation: str = "v1"):
        lockfile = root / "conan.lock"
        manifest = root / "conanfile.txt"
        lockfile.write_text('{"version":"0.5"}\n', encoding="utf-8")
        manifest.write_text("[requires]\nexample/1.0\n", encoding="utf-8")
        return build_cache_identity(
            generation=generation,
            evidence=self.evidence if evidence is None else evidence,
            lockfile=lockfile,
            dependency_files=[manifest],
        )

    def test_matching_local_and_ci_evidence_has_one_normalized_identity(self) -> None:
        local = copy.deepcopy(self.evidence)
        local["architecture"] = "arm64"
        local["options"] = dict(reversed(list(local["options"].items())))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ci_identity = self._identity(root)
            local_identity = self._identity(root, local)

        self.assertEqual(local_identity, ci_identity)
        self.assertEqual(ci_identity.architecture, "arm64")
        self.assertEqual(
            ci_identity.key,
            "rosbridge-conan-download-v1-arm64-"
            f"{ci_identity.environment_fingerprint}-{ci_identity.locked_dependency_hash}",
        )
        self.assertEqual(
            ci_identity.restore_prefix,
            "rosbridge-conan-download-v1-arm64-"
            f"{ci_identity.environment_fingerprint}-",
        )

    def test_every_compatibility_input_changes_environment_fingerprint(self) -> None:
        mutations = {
            "architecture": "x86_64",
            "os": {"id": "ubuntu", "version_id": "26.04"},
            "ros": {"distro": "kilted"},
            "compiler": {"id": "gcc", "target": "aarch64-linux-gnu", "version": "14"},
            "libc": {"id": "glibc", "version": "2.40"},
            "conan": {"version": "2.32.0"},
            "host_profile": {"settings": {"arch": "armv8", "build_type": "Debug"}},
            "build_profile": {"settings": {"arch": "armv8", "build_type": "Debug"}},
            "build_settings": {"build_type": "Debug", "compiler.cppstd": "17"},
            "options": {"grpc/*:shared": "True"},
            "shared_base": {"digest": "b" * 64},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = self._identity(root)
            for field, value in mutations.items():
                with self.subTest(field=field):
                    changed = copy.deepcopy(self.evidence)
                    changed[field] = value
                    candidate = self._identity(root, changed)
                    self.assertNotEqual(
                        candidate.environment_fingerprint,
                        baseline.environment_fingerprint,
                    )

    def test_locked_hash_covers_lockfile_and_dependency_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = self._identity(root)

            (root / "conan.lock").write_text('{"version":"0.6"}\n', encoding="utf-8")
            changed_lock = build_cache_identity(
                generation="v1",
                evidence=self.evidence,
                lockfile=root / "conan.lock",
                dependency_files=[root / "conanfile.txt"],
            )
            self.assertNotEqual(changed_lock.locked_dependency_hash, baseline.locked_dependency_hash)

            (root / "conan.lock").write_text('{"version":"0.5"}\n', encoding="utf-8")
            (root / "conanfile.txt").write_text(
                "[requires]\nexample/2.0\n",
                encoding="utf-8",
            )
            changed_manifest = build_cache_identity(
                generation="v1",
                evidence=self.evidence,
                lockfile=root / "conan.lock",
                dependency_files=[root / "conanfile.txt"],
            )
            self.assertNotEqual(
                changed_manifest.locked_dependency_hash,
                baseline.locked_dependency_hash,
            )

    def test_generation_changes_only_cache_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v1 = self._identity(root, generation="v1")
            v2 = self._identity(root, generation="v2")

        self.assertEqual(v1.environment_fingerprint, v2.environment_fingerprint)
        self.assertEqual(v1.locked_dependency_hash, v2.locked_dependency_hash)
        self.assertNotEqual(v1.restore_prefix, v2.restore_prefix)
        self.assertNotEqual(v1.key, v2.key)

    def test_simulator_only_docker_layer_does_not_change_shared_base_digest(self) -> None:
        shared = "FROM ubuntu:24.04 AS base\nRUN echo toolchain\nFROM base AS ci\n"
        dev_a = shared + "FROM base AS dev\nRUN echo gazebo-a\n"
        dev_b = shared + "FROM base AS dev\nRUN echo gazebo-b\n"

        self.assertEqual(
            shared_base_digest(dev_a, b"entrypoint-v1"),
            shared_base_digest(dev_b, b"entrypoint-v1"),
        )

    def test_shared_base_or_entrypoint_change_changes_digest(self) -> None:
        dockerfile = "FROM ubuntu:24.04 AS base\nRUN echo toolchain\nFROM base AS ci\n"
        changed = "FROM ubuntu:24.04 AS base\nRUN echo toolchain-v2\nFROM base AS ci\n"

        baseline = shared_base_digest(dockerfile, b"entrypoint-v1")
        self.assertNotEqual(baseline, shared_base_digest(changed, b"entrypoint-v1"))
        self.assertNotEqual(baseline, shared_base_digest(dockerfile, b"entrypoint-v2"))


class EnvironmentEvidenceTests(unittest.TestCase):
    def _repository(self, root: Path) -> None:
        (root / "docker").mkdir()
        (root / "docker" / "Dockerfile").write_text(
            "FROM ubuntu:24.04 AS base\nRUN echo shared\nFROM base AS ci\n"
            "FROM base AS dev\nRUN echo gazebo\n",
            encoding="utf-8",
        )
        (root / "docker" / "entrypoint.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (root / "conanfile.txt").write_text(
            "[requires]\nexample/1.0\n\n[options]\n"
            "example/*:shared=False\nexample/*:feature=True\n",
            encoding="utf-8",
        )
        (root / "conan.lock").write_text("lock", encoding="utf-8")

    def _runner(self, command) -> str:
        key = tuple(command)
        responses = {
            ("uname", "-m"): "aarch64\n",
            ("g++", "-dumpfullversion", "-dumpversion"): "13.3.0\n",
            ("g++", "-dumpmachine"): "aarch64-linux-gnu\n",
            ("getconf", "GNU_LIBC_VERSION"): "glibc 2.39\n",
            ("conan", "--version"): "Conan version 2.31.2\n",
        }
        if key[:3] == ("conan", "profile", "show"):
            return json.dumps(
                {
                    "host_profile": {"settings": {"arch": "armv8", "os": "Linux"}},
                    "build_profile": {"settings": {"arch": "armv8", "os": "Linux"}},
                }
            )
        return responses[key]

    def test_collector_covers_effective_environment_and_declared_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            os_release = root / "os-release"
            os_release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")

            evidence = collect_environment_evidence(
                root,
                host_profile="default",
                build_profile="default",
                environ={"ROS_DISTRO": "jazzy"},
                os_release=os_release,
                runner=self._runner,
            )

        self.assertEqual(evidence["architecture"], "arm64")
        self.assertEqual(evidence["os"], {"id": "ubuntu", "version_id": "24.04"})
        self.assertEqual(evidence["ros"], {"distro": "jazzy"})
        self.assertEqual(evidence["compiler"]["version"], "13.3.0")
        self.assertEqual(evidence["libc"], {"id": "glibc", "version": "2.39"})
        self.assertEqual(evidence["conan"], {"version": "2.31.2"})
        self.assertEqual(evidence["host_profile"]["settings"]["arch"], "armv8")
        self.assertEqual(evidence["build_profile"]["settings"]["arch"], "armv8")
        self.assertEqual(evidence["build_settings"]["host"]["compiler.cppstd"], "17")
        self.assertEqual(
            evidence["options"],
            {"example/*:feature": "True", "example/*:shared": "False"},
        )
        self.assertEqual(len(evidence["shared_base"]["digest"]), 64)

    def test_collector_accepts_conan_231_profile_json_schema(self) -> None:
        def conan_231_runner(command) -> str:
            if tuple(command[:3]) == ("conan", "profile", "show"):
                return json.dumps(
                    {
                        "host": {"settings": {"arch": "armv8", "os": "Linux"}},
                        "build": {"settings": {"arch": "armv8", "os": "Linux"}},
                    }
                )
            return self._runner(command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            os_release = root / "os-release"
            os_release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")

            evidence = collect_environment_evidence(
                root,
                environ={"ROS_DISTRO": "jazzy"},
                os_release=os_release,
                runner=conan_231_runner,
            )

        self.assertEqual(evidence["host_profile"]["settings"]["arch"], "armv8")
        self.assertEqual(evidence["build_profile"]["settings"]["arch"], "armv8")

    def test_cache_identity_cli_emits_same_machine_readable_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            evidence = {
                "architecture": "arm64",
                "os": {},
                "ros": {},
                "compiler": {},
                "libc": {},
                "conan": {},
                "host_profile": {},
                "build_profile": {},
                "build_settings": {},
                "options": {},
                "shared_base": {},
            }
            stdout = io.StringIO()
            argv = ["scripts.ci", "cache-identity", "--generation", "v7"]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch("scripts.ci.__main__.cache_canary.collect_environment_evidence", return_value=evidence),
                mock.patch.object(os, "getcwd", return_value=str(root)),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["generation"], "v7")
        self.assertEqual(payload["architecture"], "arm64")
        self.assertTrue(payload["key"].startswith("rosbridge-conan-download-v7-arm64-"))

    def test_required_remote_uses_loopback_tunnel_without_secret_arguments(self) -> None:
        commands = []

        def runner(command):
            commands.append(tuple(command))
            return CommandResult(0)

        configure_required_remote(
            "rosbridge",
            "http://127.0.0.1:19300",
            runner=runner,
            secrets=("credential-value",),
        )

        rendered = " ".join(item for command in commands for item in command)
        self.assertNotIn("credential-value", rendered)
        self.assertEqual(commands[0], ("conan", "profile", "detect", "--force"))
        self.assertIn(("conan", "remote", "auth", "rosbridge", "--force", "--strict"), commands)

    def test_required_remote_rejects_credentials_or_non_loopback_url(self) -> None:
        for url in (
            "http://user:password@127.0.0.1:19300",
            "http://conan.example.com:9300",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "loopback"):
                configure_required_remote("rosbridge", url)

        with self.assertRaisesRegex(ValueError, "name"):
            configure_required_remote(
                "--remote",
                "http://127.0.0.1:19300",
                runner=lambda command: self.fail("invalid remote name reached Conan"),
            )

    def test_cache_run_cli_writes_credential_free_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            evidence = {
                "architecture": "arm64",
                "os": {},
                "ros": {},
                "compiler": {},
                "libc": {},
                "conan": {},
                "host_profile": {},
                "build_profile": {},
                "build_settings": {},
                "options": {},
                "shared_base": {},
            }
            identity = build_cache_identity(
                generation="v1",
                evidence=evidence,
                lockfile=root / "conan.lock",
                dependency_files=[root / "conanfile.txt"],
            )
            cache = root / "cache"
            cache.mkdir()
            graph = root / "evidence" / "graph.json"
            result = root / "evidence" / "result.json"
            argv = [
                "scripts.ci",
                "cache-run",
                "--generation",
                "v1",
                "--sample-role",
                "producer",
                "--expected-key",
                identity.key,
                "--matched-key",
                "",
                "--remote",
                "rosbridge",
                "--remote-url",
                "http://127.0.0.1:19300",
                "--cache-dir",
                str(cache),
                "--graph-output",
                str(graph),
                "--output-folder",
                str(root / "build"),
                "--result-output",
                str(result),
                "--restore-seconds",
                "1.25",
                "--repository-cache-bytes",
                "1000",
            ]
            fake_result = mock.Mock()
            fake_result.to_dict.return_value = {"schema_version": 1, "server_verified": True}
            remote_ready = False

            def configure_remote(*args, **kwargs):
                nonlocal remote_ready
                remote_ready = True

            def collect_evidence(*args, **kwargs):
                self.assertTrue(remote_ready, "ephemeral Conan profile must exist before collection")
                return evidence

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(os, "getcwd", return_value=str(root)),
                mock.patch(
                    "scripts.ci.__main__.cache_canary.collect_environment_evidence",
                    side_effect=collect_evidence,
                ),
                mock.patch(
                    "scripts.ci.__main__.cache_canary.configure_required_remote",
                    side_effect=configure_remote,
                ),
                mock.patch(
                    "scripts.ci.__main__.cache_canary.run_canary",
                    return_value=fake_result,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = main()

            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, {"schema_version": 1, "server_verified": True})


class CacheLifecycleTests(unittest.TestCase):
    def _identity(self, root: Path, generation: str = "v1"):
        lockfile = root / "conan.lock"
        manifest = root / "conanfile.txt"
        lockfile.write_text("lock", encoding="utf-8")
        manifest.write_text("manifest", encoding="utf-8")
        evidence = {
            "architecture": "arm64",
            "os": {},
            "ros": {},
            "compiler": {},
            "libc": {},
            "conan": {},
            "host_profile": {},
            "build_profile": {},
            "build_settings": {},
            "options": {},
            "shared_base": {},
        }
        return build_cache_identity(
            generation=generation,
            evidence=evidence,
            lockfile=lockfile,
            dependency_files=[manifest],
        )

    def test_exact_key_wins_and_compatible_prefix_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = self._identity(Path(directory))

        exact = classify_cache_restore(identity, matched_key=identity.key)
        compatible = classify_cache_restore(
            identity,
            matched_key=identity.restore_prefix + "b" * 64,
        )
        miss = classify_cache_restore(identity, matched_key="")

        self.assertEqual((exact.kind, exact.cache_state), (RestoreKind.EXACT, CacheState.HIT))
        self.assertEqual(
            (compatible.kind, compatible.cache_state),
            (RestoreKind.COMPATIBLE, CacheState.HIT),
        )
        self.assertEqual((miss.kind, miss.cache_state), (RestoreKind.MISS, CacheState.MISS))

    def test_generation_or_environment_mismatch_cannot_be_restored_as_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v1 = self._identity(root, "v1")
            v2 = self._identity(root, "v2")

        with self.assertRaisesRegex(ValueError, "compatible"):
            classify_cache_restore(v2, matched_key=v1.key)

    def test_restore_service_failure_uses_strict_server_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            identity = self._identity(Path(directory))

        result = classify_cache_restore(identity, matched_key="", restore_failed=True)

        self.assertEqual(result.kind, RestoreKind.FAILURE)
        self.assertEqual(result.cache_state, CacheState.RESTORE_FAILURE)

    def test_download_cache_snapshot_proves_exact_warm_payload_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "nested").mkdir()
            (cache / "nested" / "archive.tgz").write_bytes(b"payload")

            before = inspect_download_cache(cache, secrets=("top-secret",))
            after = inspect_download_cache(cache, secrets=("top-secret",))

        self.assertEqual(before, after)
        self.assertEqual(before.files, 1)
        self.assertEqual(before.bytes, 7)

    def test_download_cache_rejects_credentials_configuration_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "credentials.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "credential-bearing"):
                inspect_download_cache(cache)

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = cache / "payload"
            target.write_bytes(b"payload")
            (cache / "link").symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                inspect_download_cache(cache)

    def test_download_cache_rejects_known_secret_without_exposing_it(self) -> None:
        secret = "credential-value-83"
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "archive.bin").write_bytes(b"prefix" + secret.encode() + b"suffix")
            with self.assertRaises(RuntimeError) as raised:
                inspect_download_cache(cache, secrets=(secret,))

        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("archive.bin", str(raised.exception))

    def test_capacity_policy_warns_and_refuses_only_at_specified_thresholds(self) -> None:
        preferred = evaluate_cache_capacity(GIB, 8 * GIB - 1)
        warning = evaluate_cache_capacity(GIB + 1, 8 * GIB)
        refused = evaluate_cache_capacity(2 * GIB + 1, 8 * GIB)

        self.assertTrue(preferred.save_allowed)
        self.assertEqual(preferred.warnings, ())
        self.assertTrue(warning.save_allowed)
        self.assertIn("1 GiB", " ".join(warning.warnings))
        self.assertIn("80%", " ".join(warning.warnings))
        self.assertFalse(refused.save_allowed)
        self.assertIn("2 GiB", refused.reason)


class GraphEvidenceTests(unittest.TestCase):
    def _write_graph(self, path: Path, package_id: str = "package-id", binary: str = "Cache"):
        path.write_text(
            json.dumps(
                {
                    "graph": {
                        "nodes": {
                            "1": {
                                "ref": "zlib/1.3.2#recipe",
                                "rrev": "recipe",
                                "package_id": package_id,
                                "prev": "package-revision",
                                "context": "host",
                                "binary": binary,
                            },
                            "0": {"ref": "conanfile", "package_id": None},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_graph_evidence_is_stable_and_sensitive_to_exact_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.json"
            self._write_graph(graph)
            baseline = read_graph_evidence(graph)
            self._write_graph(graph, package_id="changed-package-id")
            changed = read_graph_evidence(graph)

        self.assertEqual(baseline.package_count, 1)
        self.assertEqual(baseline.source_builds, ())
        self.assertNotEqual(baseline.digest, changed.digest)

    def test_graph_evidence_rejects_source_build_without_exposing_package_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = Path(directory) / "graph.json"
            self._write_graph(graph, binary="Build")
            with self.assertRaises(RuntimeError) as raised:
                read_graph_evidence(graph)

        self.assertIn("source build", str(raised.exception))
        self.assertNotIn("zlib", str(raised.exception))


class CanaryRunTests(unittest.TestCase):
    def _identity(self, root: Path):
        lockfile = root / "conan.lock"
        manifest = root / "conanfile.txt"
        lockfile.write_text("lock", encoding="utf-8")
        manifest.write_text("manifest", encoding="utf-8")
        evidence = {
            "architecture": "arm64",
            "os": {},
            "ros": {},
            "compiler": {},
            "libc": {},
            "conan": {},
            "host_profile": {},
            "build_profile": {},
            "build_settings": {},
            "options": {},
            "shared_base": {},
        }
        return build_cache_identity(
            generation="v1",
            evidence=evidence,
            lockfile=lockfile,
            dependency_files=[manifest],
        )

    def _write_graph(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "graph": {
                        "nodes": {
                            "0": {"ref": "conanfile"},
                            "1": {
                                "ref": "example/1.0#recipe",
                                "rrev": "recipe",
                                "package_id": "package-id",
                                "prev": "package-revision",
                                "context": "host",
                                "binary": "Cache",
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def _success(self, request) -> GateConclusion:
        return GateConclusion(
            success=True,
            dependency_path=DependencyPath.WARM,
            attempts=1,
            failure_class=FailureClass.NONE,
            diagnostic="Warm dependency path completed through the required Conan remote.",
            command=("conan", "install"),
        )

    def test_exact_warm_run_records_authority_graph_payload_and_timings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = self._identity(root)
            cache = root / "cache"
            cache.mkdir()
            (cache / "archive.tgz").write_bytes(b"payload")
            graph = root / "evidence" / "graph.json"
            restore = classify_cache_restore(identity, matched_key=identity.key)

            def gate_runner(request, secrets):
                self._write_graph(graph)
                return self._success(request)

            times = iter((10.0, 15.0, 20.0, 23.0))
            evidence = run_canary(
                CanaryRequest(
                    sample_role=SampleRole.WARM,
                    identity=identity,
                    restore=restore,
                    cache_dir=cache,
                    graph_file=graph,
                    output_folder=root / "build",
                    remote_name="rosbridge",
                    restore_seconds=2.5,
                    repository_cache_bytes=1000,
                ),
                gate_runner=gate_runner,
                build_runner=lambda command: CommandResult(0),
                clock=lambda: next(times),
                secrets=("credential-value",),
            )

        result = evidence.to_dict()
        self.assertTrue(result["server_verified"])
        self.assertEqual(result["restore_kind"], "exact")
        self.assertFalse(result["payload_changed"])
        self.assertEqual(result["source_builds"], [])
        self.assertEqual(result["timings_seconds"]["restore"], 2.5)
        self.assertEqual(result["timings_seconds"]["conan"], 5.0)
        self.assertEqual(result["timings_seconds"]["build"], 3.0)
        self.assertEqual(result["timings_seconds"]["total"], 10.5)

    def test_exact_warm_run_fails_if_cached_payload_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = self._identity(root)
            cache = root / "cache"
            cache.mkdir()
            archive = cache / "archive.tgz"
            archive.write_bytes(b"payload")
            graph = root / "evidence" / "graph.json"
            restore = classify_cache_restore(identity, matched_key=identity.key)

            def gate_runner(request, secrets):
                archive.write_bytes(b"re-downloaded-payload")
                self._write_graph(graph)
                return self._success(request)

            with self.assertRaisesRegex(RuntimeError, "Warm cache payload"):
                run_canary(
                    CanaryRequest(
                        sample_role=SampleRole.WARM,
                        identity=identity,
                        restore=restore,
                        cache_dir=cache,
                        graph_file=graph,
                        output_folder=root / "build",
                        remote_name="rosbridge",
                        restore_seconds=1.0,
                        repository_cache_bytes=0,
                    ),
                    gate_runner=gate_runner,
                    build_runner=lambda command: CommandResult(0),
                    clock=iter((0.0, 1.0, 1.0, 2.0)).__next__,
                )

    def test_cold_run_can_populate_payload_but_oversized_entry_is_not_saveable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = self._identity(root)
            cache = root / "cache"
            cache.mkdir()
            graph = root / "evidence" / "graph.json"
            restore = classify_cache_restore(identity, matched_key="")

            def gate_runner(request, secrets):
                (cache / "archive.tgz").write_bytes(b"payload")
                self._write_graph(graph)
                return GateConclusion(
                    success=True,
                    dependency_path=DependencyPath.COLD,
                    attempts=1,
                    failure_class=FailureClass.NONE,
                    diagnostic="Cold dependency path completed through the required Conan remote.",
                    command=("conan", "install"),
                )

            evidence = run_canary(
                CanaryRequest(
                    sample_role=SampleRole.COLD,
                    identity=identity,
                    restore=restore,
                    cache_dir=cache,
                    graph_file=graph,
                    output_folder=root / "build",
                    remote_name="rosbridge",
                    restore_seconds=1.0,
                    repository_cache_bytes=0,
                ),
                gate_runner=gate_runner,
                build_runner=lambda command: CommandResult(0),
                clock=iter((0.0, 1.0, 1.0, 2.0)).__next__,
            )

        self.assertTrue(evidence.payload_changed)
        self.assertTrue(evidence.capacity.save_allowed)

    def test_sample_role_must_match_observed_restore_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = self._identity(root)
            cache = root / "cache"
            cache.mkdir()
            restore = classify_cache_restore(identity, matched_key="")

            with self.assertRaisesRegex(RuntimeError, "sample role"):
                run_canary(
                    CanaryRequest(
                        sample_role=SampleRole.WARM,
                        identity=identity,
                        restore=restore,
                        cache_dir=cache,
                        graph_file=root / "graph.json",
                        output_folder=root / "build",
                        remote_name="rosbridge",
                        restore_seconds=1.0,
                        repository_cache_bytes=0,
                    )
                )


if __name__ == "__main__":
    unittest.main()
