"""Conan Server authorizer for the ros-sdk exact ARM64 CI reader."""

from __future__ import annotations

import json
from functools import wraps
from pathlib import Path


class ExactPackagePolicy:
    """Match recipe and package references against an exact allowlist."""

    def __init__(self, policy: dict[str, object]) -> None:
        self.username = str(policy["username"])
        self.recipe_revisions: dict[str, frozenset[str]] = {}
        mutable_recipes: dict[str, set[str]] = {}
        for value in policy["recipes"]:
            recipe, revision = self._split_revision(str(value), "recipe")
            mutable_recipes.setdefault(recipe, set()).add(revision)
        self.recipe_revisions = {
            recipe: frozenset(revisions)
            for recipe, revisions in mutable_recipes.items()
        }

        mutable_packages: dict[tuple[str, str], set[str]] = {}
        for value in policy["packages"]:
            package = str(value)
            try:
                recipe, package_reference = package.rsplit(":", maxsplit=1)
            except ValueError as error:
                raise ValueError(f"invalid package reference: {package}") from error
            package_id, revision = self._split_revision(package_reference, "package")
            if not self._allows_exact_recipe(recipe):
                raise ValueError(f"package uses an unlisted recipe revision: {package}")
            mutable_packages.setdefault((recipe, package_id), set()).add(revision)
        self.package_revisions = {
            key: frozenset(revisions) for key, revisions in mutable_packages.items()
        }

    @staticmethod
    def _split_revision(value: str, kind: str) -> tuple[str, str]:
        try:
            reference, revision = value.rsplit("#", maxsplit=1)
        except ValueError as error:
            raise ValueError(f"invalid {kind} reference: {value}") from error
        if not reference or not revision:
            raise ValueError(f"invalid {kind} reference: {value}")
        return reference, revision

    def _allows_exact_recipe(self, recipe: str) -> bool:
        reference, revision = self._split_revision(recipe, "recipe")
        return revision in self.recipe_revisions.get(reference, ())

    @staticmethod
    def _recipe(ref: object, include_revision: bool = True) -> str:
        value = f"{ref.name}/{ref.version}"
        user = getattr(ref, "user", None)
        channel = getattr(ref, "channel", None)
        if user is not None or channel is not None:
            value += f"@{user or ''}/{channel or ''}"
        revision = getattr(ref, "revision", None)
        if include_revision and revision:
            value += f"#{revision}"
        return value

    def allows_recipe(self, ref: object) -> bool:
        recipe = self._recipe(ref, include_revision=False)
        revision = getattr(ref, "revision", None)
        if revision:
            return revision in self.recipe_revisions.get(recipe, ())
        return recipe in self.recipe_revisions

    def _candidate_recipe_revisions(
        self, ref: object
    ) -> tuple[str, ...] | frozenset[str]:
        recipe = self._recipe(ref, include_revision=False)
        revision = getattr(ref, "revision", None)
        return (revision,) if revision else self.recipe_revisions.get(recipe, ())

    def allows_package(self, pref: object) -> bool:
        recipe = self._recipe(pref.ref, include_revision=False)
        package_id = pref.package_id
        package_revision = getattr(pref, "revision", None)
        allowed_revisions = {
            revision
            for allowed_recipe_revision in self._candidate_recipe_revisions(pref.ref)
            for revision in self.package_revisions.get(
                (f"{recipe}#{allowed_recipe_revision}", package_id), ()
            )
        }
        return bool(allowed_revisions) and (
            not package_revision or package_revision in allowed_revisions
        )

    def allows_recipe_revision(self, ref: object, revision: str) -> bool:
        recipe = self._recipe(ref, include_revision=False)
        return revision in self.recipe_revisions.get(recipe, ())

    def allows_package_id(self, ref: object, package_id: str) -> bool:
        recipe = self._recipe(ref, include_revision=False)
        return any(
            (f"{recipe}#{revision}", package_id) in self.package_revisions
            for revision in self._candidate_recipe_revisions(ref)
        )


class ExactReaderAuthorizer:
    """Enforce exact reads for CI and delegate every other user to Conan ACLs."""

    def __init__(self, policy: ExactPackagePolicy, fallback: object) -> None:
        self.policy = policy
        self.fallback = fallback

    def _deny(self) -> None:
        from conan.internal.errors import ForbiddenException

        raise ForbiddenException("Permission denied")

    def is_exact_reader(self, username: str) -> bool:
        return username == self.policy.username

    def check_read_conan(self, username: str, ref: object) -> None:
        if username != self.policy.username:
            self.fallback.check_read_conan(username, ref)
        elif not self.policy.allows_recipe(ref):
            self._deny()

    def check_write_conan(self, username: str, ref: object) -> None:
        if username == self.policy.username:
            self._deny()
        self.fallback.check_write_conan(username, ref)

    def check_delete_conan(self, username: str, ref: object) -> None:
        self.check_write_conan(username, ref)

    def check_read_package(self, username: str, pref: object) -> None:
        if username != self.policy.username:
            self.fallback.check_read_package(username, pref)
        elif not self.policy.allows_package(pref):
            self._deny()

    def check_write_package(self, username: str, pref: object) -> None:
        if username == self.policy.username:
            self._deny()
        self.fallback.check_write_package(username, pref)

    def check_delete_package(self, username: str, pref: object) -> None:
        self.check_write_package(username, pref)

    def filter_recipe_revisions(
        self, username: str, ref: object, revisions: list[object]
    ) -> list[object]:
        if username != self.policy.username:
            return revisions
        return [
            revision
            for revision in revisions
            if self.policy.allows_recipe_revision(ref, str(revision[0]))
        ]

    def check_recipe_revision(self, username: str, ref: object, revision: object) -> None:
        if username == self.policy.username and not self.policy.allows_recipe_revision(
            ref, str(revision[0])
        ):
            self._deny()

    def filter_package_revisions(
        self, username: str, revisions: list[object]
    ) -> list[object]:
        if username != self.policy.username:
            return revisions
        return [revision for revision in revisions if self.policy.allows_package(revision)]

    def filter_package_search(
        self, username: str, ref: object, packages: dict[str, object]
    ) -> dict[str, object]:
        if username != self.policy.username:
            return packages
        return {
            package_id: value
            for package_id, value in packages.items()
            if self.policy.allows_package_id(ref, package_id)
        }


def install_exact_read_guards(service_class: type, search_class: type) -> None:
    """Bridge Conan Server 2.x routes that omit package-level authorization."""
    if not getattr(service_class, "_rosbridge_exact_read_guards", False):
        original_recipe_revisions = service_class.get_recipe_revisions_references
        original_latest_recipe = service_class.get_latest_revision
        original_package_revisions = service_class.get_package_revisions_references
        original_latest_package = service_class.get_latest_package_reference
        original_package_file_list = service_class.get_package_file_list
        original_package_file = service_class.get_package_file

        @wraps(original_recipe_revisions)
        def recipe_revisions(self, ref, auth_user):
            revisions = original_recipe_revisions(self, ref, auth_user)
            return self._authorizer.filter_recipe_revisions(auth_user, ref, revisions)

        @wraps(original_latest_recipe)
        def latest_recipe(self, ref, auth_user):
            revision = original_latest_recipe(self, ref, auth_user)
            self._authorizer.check_recipe_revision(auth_user, ref, revision)
            return revision

        @wraps(original_package_revisions)
        def package_revisions(self, pref, auth_user):
            self._authorizer.check_read_package(auth_user, pref)
            revisions = original_package_revisions(self, pref, auth_user)
            return self._authorizer.filter_package_revisions(auth_user, revisions)

        @wraps(original_latest_package)
        def latest_package(self, pref, auth_user):
            self._authorizer.check_read_package(auth_user, pref)
            latest = original_latest_package(self, pref, auth_user)
            self._authorizer.check_read_package(auth_user, latest)
            return latest

        @wraps(original_package_file_list)
        def package_file_list(self, pref, auth_user):
            self._authorizer.check_read_package(auth_user, pref)
            return original_package_file_list(self, pref, auth_user)

        @wraps(original_package_file)
        def package_file(self, pref, filename, auth_user):
            self._authorizer.check_read_package(auth_user, pref)
            return original_package_file(self, pref, filename, auth_user)

        service_class.get_recipe_revisions_references = recipe_revisions
        service_class.get_latest_revision = latest_recipe
        service_class.get_package_revisions_references = package_revisions
        service_class.get_latest_package_reference = latest_package
        service_class.get_package_file_list = package_file_list
        service_class.get_package_file = package_file
        service_class._rosbridge_exact_read_guards = True

    if not getattr(search_class, "_rosbridge_exact_read_guards", False):
        original_search_packages = search_class.search_packages

        @wraps(original_search_packages)
        def search_packages(self, reference, list_only=False):
            # Conan's detailed search reads conaninfo.txt from the latest package
            # revision. Exact readers receive ID-only results so a newer,
            # disallowed revision cannot leak metadata through this endpoint.
            safe_list_only = list_only or self._authorizer.is_exact_reader(
                self._auth_user
            )
            packages = original_search_packages(self, reference, safe_list_only)
            return self._authorizer.filter_package_search(
                self._auth_user, reference, packages
            )

        search_class.search_packages = search_packages
        search_class._rosbridge_exact_read_guards = True


def get_class() -> ExactReaderAuthorizer:
    """Conan Server plugin entry point."""
    from conans.server.conf import ConanServerConfigParser
    from conans.server.service.authorize import BasicAuthorizer
    from conans.server.service.v2.search import SearchService
    from conans.server.service.v2.service_v2 import ConanServiceV2

    plugin_directory = Path(__file__).resolve().parent
    server_home = plugin_directory.parent.parent
    config = ConanServerConfigParser(str(server_home), is_custom_path=True)
    policy_path = plugin_directory / "rosbridge_exact_reader_policy.json"
    policy = ExactPackagePolicy(json.loads(policy_path.read_text(encoding="utf-8")))
    fallback = BasicAuthorizer(config.read_permissions, config.write_permissions)
    install_exact_read_guards(ConanServiceV2, SearchService)
    return ExactReaderAuthorizer(policy, fallback)
