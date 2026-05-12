"""Tests for template fetchers."""

import io
import json
import tarfile
import zipfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest

from copier import run_copy
from copier._fetchers import (
    GitFetcher,
    HttpFetcher,
    OciFetcher,
    OciImageRef,
    get_fetcher,
    is_remote_url,
)
from copier._template import Template


@pytest.fixture
def sample_zip_archive(tmp_path: Path) -> tuple[Path, str]:
    """Create a sample ZIP archive with template content."""
    archive_path = tmp_path / "template.zip"
    template_dir = tmp_path / "template-root"
    template_dir.mkdir()

    copier_yml = template_dir / "copier.yml"
    copier_yml.write_text("_templates_suffix: .tmpl\nname:\n  type: str\n  default: test-project\n")

    hello_tmpl = template_dir / "hello.txt.tmpl"
    hello_tmpl.write_text("Hello, {{ name }}!")

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.write(copier_yml, arcname="template-root/copier.yml")
        zf.write(hello_tmpl, arcname="template-root/hello.txt.tmpl")

    return archive_path, "Hello, test-project!"


@pytest.fixture
def sample_tar_archive(tmp_path: Path) -> tuple[Path, str]:
    """Create a sample tar.gz archive with template content."""
    archive_path = tmp_path / "template.tar.gz"
    template_dir = tmp_path / "template-root"
    template_dir.mkdir()

    copier_yml = template_dir / "copier.yml"
    copier_yml.write_text("_templates_suffix: .tmpl\nname:\n  type: str\n  default: test-project\n")

    hello_tmpl = template_dir / "hello.txt.tmpl"
    hello_tmpl.write_text("Hello, {{ name }}!")

    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(copier_yml, arcname="template-root/copier.yml")
        tf.add(hello_tmpl, arcname="template-root/hello.txt.tmpl")

    return archive_path, "Hello, test-project!"


class TestGetFetcher:
    """Tests for the get_fetcher function."""

    def test_get_fetcher_git_urls(self) -> None:
        """Test that git URLs return GitFetcher."""
        urls = [
            "git@github.com:copier-org/copier.git",
            "https://github.com/copier-org/copier.git",
            "https://gitlab.com/copier-org/copier.git",
            "gh:copier-org/copier",
            "gl:copier-org/copier",
            "git+https://example.com/repo.git",
        ]
        for url in urls:
            fetcher = get_fetcher(url)
            assert isinstance(fetcher, GitFetcher), f"Expected GitFetcher for {url}"

    def test_get_fetcher_http_urls(self) -> None:
        """Test that generic http/https URLs (not git) return HttpFetcher."""
        urls = [
            "http://example.com/template.zip",
            "https://example.com/template.tar.gz",
            "https://internal.example.com:8080/artifacts/template.zip",
            "https://example.com/path/to/template",
        ]
        for url in urls:
            fetcher = get_fetcher(url)
            assert isinstance(fetcher, HttpFetcher), f"Expected HttpFetcher for {url}"

    def test_get_fetcher_oci_urls(self) -> None:
        """Test that OCI URLs return OciFetcher."""
        urls = [
            "oci://registry.example.com/my-template:v1.0.0",
            "docker://registry.example.com/my-template:latest",
        ]
        for url in urls:
            fetcher = get_fetcher(url)
            assert isinstance(fetcher, OciFetcher), f"Expected OciFetcher for {url}"

    def test_get_fetcher_local_path(self) -> None:
        """Test that local paths return None."""
        paths = [
            "/path/to/template",
            "./relative/path",
            "tests/demo",
        ]
        for path in paths:
            fetcher = get_fetcher(path)
            assert fetcher is None, f"Expected None for local path {path}"

    def test_protocol_detection_priority(self) -> None:
        """Test that URL detection has correct priority."""
        git_url = "https://github.com/copier-org/copier.git"
        oci_url = "oci://registry.example.com/image:v1"
        http_url = "https://example.com/archive.zip"

        assert isinstance(get_fetcher(git_url), GitFetcher)
        assert isinstance(get_fetcher(oci_url), OciFetcher)
        assert isinstance(get_fetcher(http_url), HttpFetcher)


class TestIsRemoteUrl:
    """Tests for the is_remote_url function."""

    def test_is_remote_url_git(self) -> None:
        """Test git URLs are recognized as remote."""
        assert is_remote_url("https://github.com/copier-org/copier.git")
        assert is_remote_url("gh:copier-org/copier")

    def test_is_remote_url_http(self) -> None:
        """Test http/https URLs are recognized as remote."""
        assert is_remote_url("http://example.com/template.zip")
        assert is_remote_url("https://example.com/template.tar.gz")

    def test_is_remote_url_oci(self) -> None:
        """Test OCI URLs are recognized as remote."""
        assert is_remote_url("oci://registry.example.com/template:v1")
        assert is_remote_url("docker://registry.example.com/template:latest")

    def test_is_remote_url_local(self) -> None:
        """Test local paths are not recognized as remote."""
        assert not is_remote_url("/local/path")
        assert not is_remote_url("./tests/demo")


class TestGitFetcher:
    """Tests for GitFetcher."""

    def test_git_fetcher_protocol(self) -> None:
        """Test GitFetcher protocol is 'git'."""
        fetcher = GitFetcher()
        assert fetcher.protocol == "git"

    def test_git_fetcher_can_handle(self) -> None:
        """Test GitFetcher.can_handle for git URLs."""
        fetcher = GitFetcher()
        assert fetcher.can_handle("https://github.com/copier-org/copier.git")
        assert fetcher.can_handle("gh:copier-org/copier")
        assert not fetcher.can_handle("https://example.com/archive.zip")
        assert not fetcher.can_handle("oci://registry.example.com/image:v1")


class TestHttpFetcher:
    """Tests for HttpFetcher."""

    def test_http_fetcher_protocol(self) -> None:
        """Test HttpFetcher protocol is 'http'."""
        fetcher = HttpFetcher()
        assert fetcher.protocol == "http"

    def test_can_handle_http(self) -> None:
        """Test HttpFetcher can handle http/https URLs."""
        fetcher = HttpFetcher()
        assert fetcher.can_handle("http://example.com/file.zip")
        assert fetcher.can_handle("https://example.com/file.tar.gz")

    def test_extract_zip(self, sample_zip_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test extracting ZIP archives."""
        archive_path, _ = sample_zip_archive
        fetcher = HttpFetcher()

        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = archive_path.read_bytes()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = fetcher.fetch("https://example.com/template.zip", location=str(tmp_path / "fetch"))
            result_path = Path(result)

            assert result_path.exists()
            assert (result_path / "copier.yml").exists()
            assert (result_path / "hello.txt.tmpl").exists()

    def test_extract_tar(self, sample_tar_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test extracting tar.gz archives."""
        archive_path, _ = sample_tar_archive
        fetcher = HttpFetcher()

        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = archive_path.read_bytes()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = fetcher.fetch("https://example.com/template.tar.gz", location=str(tmp_path / "fetch"))
            result_path = Path(result)

            assert result_path.exists()
            assert (result_path / "copier.yml").exists()
            assert (result_path / "hello.txt.tmpl").exists()

    def test_authorization_header_with_token(self, sample_zip_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test Authorization header is set when ref is a token."""
        archive_path, _ = sample_zip_archive
        fetcher = HttpFetcher()

        captured_headers: dict = {}

        def mock_request(url, headers=None):
            nonlocal captured_headers
            captured_headers = headers or {}
            req = MagicMock()
            return req

        with mock.patch("urllib.request.Request", side_effect=mock_request):
            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = archive_path.read_bytes()
                mock_urlopen.return_value.__enter__.return_value = mock_response

                fetcher.fetch(
                    "https://example.com/template.zip",
                    ref="my-secret-token",
                    location=str(tmp_path / "fetch"),
                )

                assert "Authorization" in captured_headers
                assert captured_headers["Authorization"] == "Bearer my-secret-token"

    def test_authorization_header_not_set_for_digest(self, sample_zip_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test Authorization header is not set when ref is a digest."""
        archive_path, _ = sample_zip_archive
        fetcher = HttpFetcher()

        captured_headers: dict = {}

        def mock_request(url, headers=None):
            nonlocal captured_headers
            captured_headers = headers or {}
            req = MagicMock()
            return req

        with mock.patch("urllib.request.Request", side_effect=mock_request):
            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = archive_path.read_bytes()
                mock_urlopen.return_value.__enter__.return_value = mock_response

                fetcher.fetch(
                    "https://example.com/template.zip",
                    ref="sha256:abc123def456",
                    location=str(tmp_path / "fetch"),
                )

                assert captured_headers == {}


class TestOciImageRef:
    """Tests for OciImageRef parsing."""

    def test_parse_simple_docker_hub_image(self) -> None:
        """Test parsing simple Docker Hub image reference."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("nginx:latest")
        assert ref.registry == "registry-1.docker.io"
        assert ref.repository == "nginx"
        assert ref.tag == "latest"
        assert ref.digest is None

    def test_parse_with_namespace(self) -> None:
        """Test parsing image with namespace."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("library/nginx:1.25")
        assert ref.registry == "registry-1.docker.io"
        assert ref.repository == "library/nginx"
        assert ref.tag == "1.25"
        assert ref.digest is None

    def test_parse_custom_registry(self) -> None:
        """Test parsing image with custom registry."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("registry.example.com/my-image:v1.0.0")
        assert ref.registry == "registry.example.com"
        assert ref.repository == "my-image"
        assert ref.tag == "v1.0.0"
        assert ref.digest is None

    def test_parse_custom_registry_with_port(self) -> None:
        """Test parsing image with custom registry and port."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("registry.example.com:5000/my-image:v1.0.0")
        assert ref.registry == "registry.example.com:5000"
        assert ref.repository == "my-image"
        assert ref.tag == "v1.0.0"
        assert ref.digest is None

    def test_parse_with_digest(self) -> None:
        """Test parsing image with digest."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("nginx@sha256:abc123def456")
        assert ref.registry == "registry-1.docker.io"
        assert ref.repository == "nginx"
        assert ref.tag is None
        assert ref.digest == "sha256:abc123def456"

    def test_parse_with_tag_and_digest(self) -> None:
        """Test parsing image with both tag and digest (digest wins)."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("nginx:latest@sha256:abc123def456")
        assert ref.repository == "nginx"
        assert ref.tag is None
        assert ref.digest == "sha256:abc123def456"

    def test_parse_no_tag(self) -> None:
        """Test parsing image without tag."""
        fetcher = OciFetcher()
        ref = fetcher._parse_oci_reference("nginx")
        assert ref.repository == "nginx"
        assert ref.tag is None
        assert ref.digest is None

    def test_parse_oci_url_prefixes(self) -> None:
        """Test parsing OCI URLs with different prefixes."""
        fetcher = OciFetcher()

        ref1 = fetcher._parse_oci_url("oci://registry.example.com/image:v1")
        assert ref1.registry == "registry.example.com"
        assert ref1.repository == "image"
        assert ref1.tag == "v1"

        ref2 = fetcher._parse_oci_url("docker://registry.example.com/image:latest")
        assert ref2.registry == "registry.example.com"
        assert ref2.repository == "image"
        assert ref2.tag == "latest"


class TestOciFetcher:
    """Tests for OciFetcher."""

    def test_oci_fetcher_protocol(self) -> None:
        """Test OciFetcher protocol is 'oci'."""
        fetcher = OciFetcher()
        assert fetcher.protocol == "oci"

    def test_can_handle_oci_prefixes(self) -> None:
        """Test OciFetcher can handle OCI prefixed URLs."""
        fetcher = OciFetcher()
        assert fetcher.can_handle("oci://registry.example.com/image:v1")
        assert fetcher.can_handle("docker://registry.example.com/image:latest")

    def test_fetch_with_ref_param(self, sample_tar_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test OciFetcher fetch with ref parameter."""
        archive_path, _ = sample_tar_archive
        fetcher = OciFetcher()

        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "layers": [
                {
                    "digest": "sha256:abcd1234",
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": 1234,
                }
            ],
        }

        def mock_make_request(url: str, token: str | None = None, accept: str = "*/*") -> bytes:
            if "/manifests/" in url:
                return json.dumps(manifest).encode()
            elif "/blobs/" in url:
                return archive_path.read_bytes()
            return b""

        with mock.patch.object(fetcher, "_make_request", side_effect=mock_make_request):
            with mock.patch.object(fetcher, "_get_auth_token", return_value="test-token"):
                result = fetcher.fetch(
                    "oci://registry.example.com/image",
                    ref="v1.0.0",
                    location=str(tmp_path / "fetch"),
                )
                result_path = Path(result)

                assert result_path.exists()
                assert (result_path / "copier.yml").exists()

    def test_fetch_with_digest_ref(self, sample_tar_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test OciFetcher fetch with digest ref parameter."""
        archive_path, _ = sample_tar_archive
        fetcher = OciFetcher()

        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "layers": [
                {
                    "digest": "sha256:abcd1234",
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": 1234,
                }
            ],
        }

        def mock_make_request(url: str, token: str | None = None, accept: str = "*/*") -> bytes:
            if "/manifests/sha256:" in url:
                return json.dumps(manifest).encode()
            elif "/blobs/" in url:
                return archive_path.read_bytes()
            return b""

        with mock.patch.object(fetcher, "_make_request", side_effect=mock_make_request):
            with mock.patch.object(fetcher, "_get_auth_token", return_value="test-token"):
                result = fetcher.fetch(
                    "oci://registry.example.com/image",
                    ref="sha256:abc123def456",
                    location=str(tmp_path / "fetch"),
                )
                result_path = Path(result)

                assert result_path.exists()
                assert (result_path / "copier.yml").exists()


class TestTemplateWithFetchers:
    """Tests for Template class with new fetchers."""

    def test_template_vcs_property_git(self) -> None:
        """Test Template.vcs returns 'git' for git URLs."""
        template = Template(url="https://github.com/copier-org/copier.git")
        assert template.vcs == "git"

    def test_template_vcs_property_http(self) -> None:
        """Test Template.vcs returns 'http' for http URLs."""
        template = Template(url="https://example.com/template.zip")
        assert template.vcs == "http"

    def test_template_vcs_property_oci(self) -> None:
        """Test Template.vcs returns 'oci' for OCI URLs."""
        template = Template(url="oci://registry.example.com/template:v1")
        assert template.vcs == "oci"

    def test_template_vcs_property_local(self) -> None:
        """Test Template.vcs returns None for local paths."""
        template = Template(url="tests/demo")
        assert template.vcs is None

    def test_template_with_http_fetcher(
        self, sample_zip_archive: tuple[Path, str], tmp_path: Path
    ) -> None:
        """Test Template using HttpFetcher with mock."""
        archive_path, expected_content = sample_zip_archive

        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = archive_path.read_bytes()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            dst = tmp_path / "output"
            run_copy(
                src_path="https://example.com/template.zip",
                dst_path=dst,
                defaults=True,
            )

            assert (dst / "hello.txt").exists()
            assert (dst / "hello.txt").read_text() == expected_content

    def test_template_local_path(self, tmp_path: Path) -> None:
        """Test Template with local path (no fetcher)."""
        template = Template(url="tests/demo")
        assert template.vcs is None
        assert template.local_abspath.exists()
        assert (template.local_abspath / "copier.yaml").exists()
