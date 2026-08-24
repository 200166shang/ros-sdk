import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from conan.internal.errors import ForbiddenException

from scripts.ci.conan_exact_reader_authorizer import (
    ExactPackagePolicy,
    ExactReaderAuthorizer,
    install_exact_read_guards,
)


class ConanExactReaderAuthorizerTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = json.loads(
            Path("scripts/ci/conan_arm64_packages.json").read_text(encoding="utf-8")
        )
        self.policy = ExactPackagePolicy(raw)
        self.recipe = SimpleNamespace(
            name="grpc",
            version="1.82.0",
            revision="854077a504a256205bdc03c1156bb782",
        )
        self.package = SimpleNamespace(
            ref=self.recipe,
            package_id="b8cf8d37e501e489e0eaa3b565846024f5a0065b",
            revision="438557092d92ee51e6500c86d0a75d79",
        )

    def test_policy_allows_only_manifest_recipe_and_package(self) -> None:
        self.assertTrue(self.policy.allows_recipe(self.recipe))
        self.assertTrue(self.policy.allows_package(self.package))
        self.package.package_id = "different-architecture-package-id"
        self.assertFalse(self.policy.allows_package(self.package))

    def test_policy_allows_server_queries_before_revision_is_selected(self) -> None:
        self.recipe.revision = None
        self.package.revision = None

        self.assertTrue(self.policy.allows_recipe(self.recipe))
        self.assertTrue(self.policy.allows_package(self.package))

    def test_policy_rejects_malformed_package_references_during_loading(self) -> None:
        raw = json.loads(
            Path("scripts/ci/conan_arm64_packages.json").read_text(encoding="utf-8")
        )
        raw["packages"] = ["malformed"]

        with self.assertRaisesRegex(ValueError, "invalid package reference"):
            ExactPackagePolicy(raw)

    def test_ci_reader_cannot_write_and_other_users_keep_existing_acl(self) -> None:
        fallback = mock.Mock()
        authorizer = ExactReaderAuthorizer(self.policy, fallback)

        authorizer.check_read_package("maintainer", self.package)
        fallback.check_read_package.assert_called_once_with("maintainer", self.package)
        with self.assertRaises(ForbiddenException):
            authorizer.check_write_package("ros-sdk-ci-reader", self.package)

    def test_server_read_guards_enforce_package_ids_and_filter_revision_queries(self) -> None:
        class Service:
            def get_recipe_revisions_references(self, ref, auth_user):
                return [("854077a504a256205bdc03c1156bb782", 1), ("other", 2)]

            def get_latest_revision(self, ref, auth_user):
                return ("854077a504a256205bdc03c1156bb782", 1)

            def get_package_revisions_references(self, pref, auth_user):
                allowed = SimpleNamespace(
                    ref=pref.ref,
                    package_id=pref.package_id,
                    revision="438557092d92ee51e6500c86d0a75d79",
                )
                denied = SimpleNamespace(
                    ref=pref.ref,
                    package_id=pref.package_id,
                    revision="other",
                )
                return [allowed, denied]

            def get_latest_package_reference(self, pref, auth_user):
                return SimpleNamespace(
                    ref=pref.ref,
                    package_id=pref.package_id,
                    revision="438557092d92ee51e6500c86d0a75d79",
                )

            def get_package_file_list(self, pref, auth_user):
                return {"files": {}}

            def get_package_file(self, pref, filename, auth_user):
                return filename

        class Search:
            def search_packages(self, reference, list_only=False):
                return {
                    "b8cf8d37e501e489e0eaa3b565846024f5a0065b": (
                        {} if list_only else {"content": "newer-disallowed-metadata"}
                    ),
                    "different-architecture-package-id": (
                        {} if list_only else {"content": "wrong-architecture"}
                    ),
                }

        install_exact_read_guards(Service, Search)
        authorizer = ExactReaderAuthorizer(self.policy, mock.Mock())
        service = Service()
        service._authorizer = authorizer
        search = Search()
        search._authorizer = authorizer
        search._auth_user = "ros-sdk-ci-reader"

        self.assertEqual(
            service.get_recipe_revisions_references(
                self.recipe, "ros-sdk-ci-reader"
            ),
            [("854077a504a256205bdc03c1156bb782", 1)],
        )
        self.assertEqual(
            len(
                service.get_package_revisions_references(
                    self.package, "ros-sdk-ci-reader"
                )
            ),
            1,
        )
        self.assertEqual(
            search.search_packages(self.recipe),
            {"b8cf8d37e501e489e0eaa3b565846024f5a0065b": {}},
        )
        self.package.package_id = "different-architecture-package-id"
        with self.assertRaises(ForbiddenException):
            service.get_package_file_list(self.package, "ros-sdk-ci-reader")


if __name__ == "__main__":
    unittest.main()
