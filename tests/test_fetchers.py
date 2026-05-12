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
    FETCHER_PREFIX,
    GitFetcher,
    HttpFetcher,
    OciFetcher,
    TemplateFetcher,
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
    copier_yml.write_text("name:\n  type: str\n  default: test-project\n")

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
    copier_yml.write_text("name:\n  type: str\n  default: test-project\n")

    hello_tmpl = template_dir / "hello.txt.tmpl"
    hello_tmpl.write_text("Hello, {{ name }}!")

    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(copier_yml, arcname="template-root/copier.yml")
        tf.add(hello_tmpl, arcname="template-root/hello.txt.tmpl")

    return archive_path, "Hello, test-project!"


class TestGetFetcher:
    """Tests for the get_fetcher function."""

    def test_get_fetcher_git(self) -> None:
        """Test that git URLs return GitFetcher."""
        urls = [
            "git@github.com:copier-org/copier.git",
            "https://github.com/copier-org/copier.git",
            "gh:copier-org/copier",
            "gl:copier-org/copier",
            "git+https://example.com/repo.git",
        ]
        for url in urls:
            fetcher = get_fetcher(url)
            assert isinstance(fetcher, GitFetcher), f"Expected GitFetcher for {url}"

    def test_get_fetcher_http(self) -> None:
        """Test that http/https URLs return HttpFetcher."""
        urls = [
            "http://example.com/template.zip",
            "https://example.com/template.tar.gz",
            "https://internal.example.com:8080/artifacts/template.zip",
        ]
        for url in urls:
            fetcher = get_fetcher(url)
            assert isinstance(fetcher, HttpFetcher), f"Expected HttpFetcher for {url}"

    def test_get_fetcher_oci(self) -> None:
        """Test that OCI URLs return OciFetcher."""
        urls = [
            "oci://registry.example.com/my-template:v1.0.0",
            "docker://registry.example.com/my-template:latest",
            "registry.example.com/my-template@sha256:abc123",
        ]
        for url in urls:
            fetcher = get_fetcher(url)
            assert isinstance(fetcher, OciFetcher), f"Expected OciFetcher for {url}"

    def test_get_fetcher_local_path(self) -> None:
        """Test that local paths return None."""
        paths = [
            "/path/to/template",
            "./relative/path",
            "C:\\Windows\\path",
            "tests/demo",
        ]
        for path in paths:
            fetcher = get_fetcher(path)
            assert fetcher is None, f"Expected None for local path {path}"


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

    def test_is_remote_url_local(self) -> None:
        """Test local paths are not recognized as remote."""
        assert not is_remote_url("/local/path")
        assert not is_remote_url("./tests/demo")


class TestHttpFetcher:
    """Tests for HttpFetcher."""

    def test_can_handle_http(self) -> None:
        """Test HttpFetcher can handle http/https URLs."""
        fetcher = HttpFetcher()
        assert fetcher.can_handle("http://example.com/file.zip")
        assert fetcher.can_handle("https://example.com/file.tar.gz")
        assert not fetcher.can_handle("git@example.com:repo.git")
        assert not fetcher.can_handle("oci://registry.example.com/image")

    def test_extract_zip(self, sample_zip_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test extracting ZIP archives."""
        archive_path, _ = sample_zip_archive
        fetcher = HttpFetcher()

        extracted = tmp_path / "extracted"
        extracted.mkdir()

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


class TestOciFetcher:
    """Tests for OciFetcher."""

    def test_can_handle_oci(self) -> None:
        """Test OciFetcher can handle OCI URLs."""
        fetcher = OciFetcher()
        assert fetcher.can_handle("oci://registry.example.com/image:v1")
        assert fetcher.can_handle("docker://registry.example.com/image:latest")
        assert fetcher.can_handle("registry.example.com/image@sha256:abc123")
        assert not fetcher.can_handle("https://example.com/file.zip")

    def test_parse_oci_url(self) -> None:
        """Test parsing OCI URLs."""
        fetcher = OciFetcher()
        assert fetcher._parse_oci_url("oci://registry.example.com/image:v1") == "registry.example.com/image:v1"
        assert fetcher._parse_oci_url("docker://registry.example.com/image:latest") == "registry.example.com/image:latest"
        assert fetcher._parse_oci_url("registry://example.com/image") == "example.com/image"
        assert fetcher._parse_oci_url("plain.reference/image:tag") == "plain.reference/image:tag"

    def test_fetch_with_mock(self, sample_tar_archive: tuple[Path, str], tmp_path: Path) -> None:
        """Test OCI fetcher with mocked responses."""
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
                result = fetcher.fetch("oci://registry.example.com/image:v1", location=str(tmp_path / "fetch"))
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
            worker = run_copy(
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
