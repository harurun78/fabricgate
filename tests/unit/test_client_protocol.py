"""Runtime conformance for the client boundary Protocol (G3).

The static (mypy) check lives in registry_client.py; this verifies the
runtime-checkable surface and that a non-RegistryClient conformant object
is accepted (drop-in).
"""

from __future__ import annotations

from fabricgate.client.registry_client import RegistryClient, RegistryClientProtocol


def test_registry_client_satisfies_protocol() -> None:
    with RegistryClient(base_url="http://localhost:8000/api/v1") as client:
        assert isinstance(client, RegistryClientProtocol)


def test_minimal_conformant_fake_is_accepted() -> None:
    class _FakeClient:
        def get_version(self, namespace, design, version):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def get_dependencies(self, namespace, design, version, board_id, runtime, *, include_optional=False):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def get_shell(self, namespace, design, version, board_id, runtime):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def get_platform_manifest_bytes(self, namespace, design, version, board_id, runtime):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def download_artifact(self, namespace, design, version, board_id, runtime, filename):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def create_artifact_uploads(self, namespace, design, artifacts):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def upload_artifact(self, ticket, data):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def publish_version(self, namespace, design, version, files):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def get_namespace_quota(self, namespace):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    assert isinstance(_FakeClient(), RegistryClientProtocol)


def test_missing_method_is_not_conformant() -> None:
    class _Incomplete:
        def get_version(self, namespace, design, version):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    assert not isinstance(_Incomplete(), RegistryClientProtocol)
