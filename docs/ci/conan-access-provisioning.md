# Restricted Conan CI access

Issue #81 is provisioned by a maintainer after the provisioning change is present on the trusted
branch:

```bash
./scripts/provision_conan_ci.sh
```

The wizard creates a repository-specific Ed25519 key, installs a dedicated tunnel account, creates a
read-only Conan identity, writes the required GitHub Secrets, and dispatches the trusted ARM64 smoke
workflow. It never writes credentials to `.env`, the repository, an artifact, or a cache. Temporary
private-key and password files use owner-only permissions and are deleted on exit.

## Code layout

This flow is called **Conan CI 访问配置编排**. The stable shell command is only the entry point. The
Python module `scripts/ci/conan_access_provisioning.py` owns the seven stages in order, while the
`SshAdapter`, `GitHubAdapter`, and `CommandAdapter` keep external commands at explicit seams. The
wizard stops at the first failed stage; re-running it performs the checks again instead of resuming a
partially saved progress file.

The Python code intentionally uses small data classes and ordinary functions. The single complete-flow
test uses fake adapters, so the stage order can be checked without contacting a real server or GitHub.

## Before running

The maintainer needs:

- repository administration permission through an authenticated `gh` CLI;
- an SSH administrator account that can run `sudo` on the Conan host;
- an independently trusted copy of the SSH host-key fingerprints, obtained from the server console or
  hosting-provider control plane;
- the Conan Server configuration path and supervisor service name.

The wizard installs the `rosbridge_exact_reader` Conan authorizer plugin and adds only the dedicated CI
user. Existing `[read_permissions]`, `[write_permissions]`, and other users remain unchanged; the plugin
delegates every non-CI identity to those existing rules. The updater backs up the original configuration
beside it as `server.conf.bak.<UTC timestamp>` before an atomic replacement.

Conan Server's built-in ACL is recipe-reference based, not binary-package-ID based. The custom authorizer
closes that gap for the CI identity: recipe reads require an exact locked recipe revision, package reads
require an allowlisted package ID and package revision, and all write/delete operations are denied. The
allowlist records the Linux ARM64 Conan profile used to produce those IDs and is checked against
`conan.lock` before provisioning. The smoke workflow selects the same graph with `arch=armv8` and
`--build=never`; a missing exact binary fails instead of compiling from source. This follows Conan's
documented custom-authorizer model and read-only CI guidance:
[Conan Server permissions](https://docs.conan.io/2/reference/conan_server.html) and
[Conan security guidelines](https://docs.conan.io/2/security/guidelines.html).

Conan Server 2.x defines package-level authorizer hooks but its package download routes call only the
recipe-level hook. The plugin therefore installs guarded wrappers around those known read routes, filters
recipe/package revision and package-search results, and fails to load if that server API is incompatible.
This compatibility behavior is exercised against the real `conan-server` package in validation.

Whenever `conan.lock` or the ARM64 CI profile changes, regenerate
`scripts/ci/conan_arm64_packages.json` from a trusted ARM64 Conan graph before provisioning. The wizard
refuses a manifest whose recipe revisions or complete profile no longer match the repository inputs.

## SSH restrictions

The dedicated operating-system account has a `nologin` shell. Its key receives both per-key and
account-level restrictions:

- `restrict` disables PTY, agent forwarding, X11 forwarding, and user rc execution;
- `port-forwarding` re-enables forwarding for the key, while `permitopen` limits it to the literal Conan
  service address and port;
- the `sshd` `Match User` block allows local TCP forwarding only, disables Unix-socket forwarding,
  denies remote listeners, and repeats the target restriction; and
- password and keyboard-interactive authentication are disabled.

The installer validates the complete `sshd` configuration and checks the effective dedicated-user
settings before reloading the daemon. These options follow the OpenSSH
[`authorized_keys` restrictions](https://man.openbsd.org/sshd.8) and
[`sshd_config` forwarding controls](https://man.openbsd.org/sshd_config).

## GitHub configuration

The wizard streams these repository Secrets through `gh secret set`:

| Secret | Purpose |
|---|---|
| `CONAN_SSH_PRIVATE_KEY` | Dedicated Ed25519 private key |
| `CONAN_SSH_KNOWN_HOSTS` | Independently verified SSH host keys |
| `CONAN_SSH_HOST` / `CONAN_SSH_PORT` | Public SSH endpoint |
| `CONAN_SSH_USER` | Dedicated tunnel operating-system user |
| `CONAN_SSH_TARGET_HOST` / `CONAN_SSH_TARGET_PORT` | Allowed Conan forwarding target |
| `CONAN_LOGIN_USERNAME` / `CONAN_PASSWORD` | Dedicated Conan reader credentials |

It also records non-sensitive `CONAN_SSH_KEY_ID` and `CONAN_SSH_ROTATE_AFTER` repository variables. The
smoke workflow is `workflow_dispatch` only, runs only from `main`, has `contents: read`, and does not
upload artifacts or save a cache. Its ARM64 container image is pinned by digest. The wizard gives each
dispatch a unique correlation ID and watches that exact run before removing an old key. The workflow
verifies strict host identity, tunnel establishment,
`/v1/ping`, authentication, live write denial against a unique nonexistent target, and locked ARM64
package reads in a disposable Conan home. GitHub documents repository-secret creation and CLI use
in [Using secrets in GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## Rotation and emergency revocation

Rotate on or before the recorded 180-day date:

1. Re-run the wizard and provide the current `CONAN_SSH_KEY_ID` as the old rotation key.
2. The wizard adds a fresh Ed25519 key without removing the old key.
3. It keeps the existing Conan password and updates the SSH-related GitHub Secrets, avoiding a
   credential cutover during the overlap window.
4. The trusted smoke workflow must pass.
5. Only then does the wizard remove the old SSH key.

For suspected exposure, re-run immediately and enter the compromised key ID at Stage 1. The wizard
removes that key before creating a replacement; availability is secondary to revocation in this path.
Afterward complete the normal provisioning and smoke stages. If Conan credentials may also be exposed,
the newly generated password replaces the old one when the server configuration is applied.

To roll back a bad Conan authorizer change, restore the timestamped `server.conf` backup, remove or fix the
plugin, and restart Conan Server. Do not restore a revoked SSH key after suspected compromise.
