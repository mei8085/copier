"""Template fetchers for different protocols."""

from __future__ import annotations

import io
import json
import re
import tarfile
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import mkdtemp
from typing import Literal
from zipfile import ZipFile

from ._vcs import (
    clone as git_clone,
    get_latest_tag,
    get_repo,
    is_git_available,
)

FETCHER_PREFIX = f"{__name__}.fetcher."


class TemplateFetcher(ABC):
    """Abstract base class for template fetchers."""

    protocol: Literal["git", "http", "https", "oci"]

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this fetcher can handle the given URL."""

    @abstractmethod
    def fetch(
        self,
        url: str,
        ref: str | None = None,
        location: str | None = None,
        use_prereleases: bool = False,
    ) -> str:
        """Fetch template from URL to local directory.

        Args:
            url: URL of the template source.
            ref: Optional reference (tag, branch, commit, digest, etc.).
            location: Optional pre-allocated directory to fetch into.
            use_prereleases: Whether to use prerelease versions when auto-selecting ref.

        Returns:
            Path to the fetched template directory.
        """


class GitFetcher(TemplateFetcher):
    """Fetcher for git repositories."""

    protocol: Literal["git"] = "git"

    def can_handle(self, url: str) -> bool:
        if not is_git_available():
            return False
        return get_repo(url) is not None

    def fetch(
        self,
        url: str,
        ref: str | None = None,
        location: str | None = None,
        use_prereleases: bool = False,
    ) -> str:
        repo_url = get_repo(url) or url
        if ref is None:
            ref = get_latest_tag(repo_url, use_prereleases)
        return git_clone(repo_url, ref, location)


class HttpFetcher(TemplateFetcher):
    """Fetcher for http/https URLs (archives or direct downloads)."""

    protocol: Literal["http"] = "http"

    HTTP_PREFIXES = ("http://", "https://")
    ARCHIVE_EXTENSIONS = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".zip")

    def can_handle(self, url: str) -> bool:
        return url.startswith(self.HTTP_PREFIXES)

    def fetch(
        self,
        url: str,
        ref: str | None = None,
        location: str | None = None,
        use_prereleases: bool = False,
    ) -> str:
        if location is None:
            location = mkdtemp(prefix=FETCHER_PREFIX)

        import urllib.request

        headers = {}
        if ref:
            headers["Authorization"] = f"Bearer {ref}" if not ref.startswith(("sha256:", "md5:")) else ""

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            content = response.read()

        archive_path = Path(location) / "archive"
        archive_path.write_bytes(content)

        extracted_path = Path(location) / "extracted"
        extracted_path.mkdir(parents=True, exist_ok=True)

        if self._is_zip(content):
            self._extract_zip(archive_path, extracted_path)
        elif self._is_tar(content):
            self._extract_tar(archive_path, extracted_path)
        else:
            raise ValueError(f"Unsupported archive format for URL: {url}")

        result = self._find_template_root(extracted_path)
        return str(result)

    def _is_zip(self, content: bytes) -> bool:
        return zipfile.is_zipfile(io.BytesIO(content))

    def _is_tar(self, content: bytes) -> bool:
        try:
            with tarfile.open(fileobj=io.BytesIO(content)):
                return True
        except tarfile.TarError:
            return False

    def _extract_zip(self, archive_path: Path, dest: Path) -> None:
        with ZipFile(archive_path, "r") as zf:
            zf.extractall(dest)

    def _extract_tar(self, archive_path: Path, dest: Path) -> None:
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest)

    def _find_template_root(self, extracted_path: Path) -> Path:
        items = list(extracted_path.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return extracted_path


class OciFetcher(TemplateFetcher):
    """Fetcher for OCI registries."""

    protocol: Literal["oci"] = "oci"

    OCI_PREFIXES = ("oci://", "docker://", "registry://")

    def can_handle(self, url: str) -> bool:
        return url.startswith(self.OCI_PREFIXES) or self._is_oci_reference(url)

    def fetch(
        self,
        url: str,
        ref: str | None = None,
        location: str | None = None,
        use_prereleases: bool = False,
    ) -> str:
        if location is None:
            location = mkdtemp(prefix=FETCHER_PREFIX)

        image_ref = self._parse_oci_url(url)
        if ref and "@" not in image_ref and ":" not in image_ref.rsplit("/", 1)[-1]:
            image_ref = f"{image_ref}:{ref}"

        layers = self._download_oci_artifact(image_ref)
        extracted_path = Path(location) / "extracted"
        extracted_path.mkdir(parents=True, exist_ok=True)

        for layer_data in layers:
            if layer_data:
                self._extract_layer(layer_data, extracted_path)

        result = self._find_template_root(extracted_path)
        return str(result)

    def _parse_oci_url(self, url: str) -> str:
        for prefix in self.OCI_PREFIXES:
            if url.startswith(prefix):
                return url[len(prefix):]
        return url

    def _is_oci_reference(self, url: str) -> bool:
        oci_pattern = r"^([a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?/)?[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*(?:[:@][a-zA-Z0-9_.-]+)?$"
        return bool(re.match(oci_pattern, url))

    def _download_oci_artifact(self, image_ref: str) -> list[bytes]:
        import urllib.request

        if "@" in image_ref:
            name_part, digest = image_ref.rsplit("@", 1)
        elif ":" in image_ref and not image_ref.startswith("http"):
            parts = image_ref.rsplit(":", 1)
            if "/" in parts[1]:
                name_part = image_ref
                tag = "latest"
            else:
                name_part, tag = parts
        else:
            name_part = image_ref
            tag = "latest"

        if "/" in name_part:
            registry, rest = name_part.split("/", 1)
            if "." in registry or ":" in registry:
                repository = rest
            else:
                registry = "registry-1.docker.io"
                repository = name_part
        else:
            registry = "registry-1.docker.io"
            repository = name_part

        registry_url = f"https://{registry}"

        token = self._get_auth_token(registry_url, repository)

        manifest_url = f"{registry_url}/v2/{repository}/manifests/{tag}"
        manifest = self._make_request(manifest_url, token, accept="application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json")

        manifest_json = json.loads(manifest)
        layers: list[bytes] = []

        for layer in manifest_json.get("layers", []):
            digest = layer["digest"]
            layer_url = f"{registry_url}/v2/{repository}/blobs/{digest}"
            layer_data = self._make_request(layer_url, token)
            layers.append(layer_data)

        return layers

    def _get_auth_token(self, registry_url: str, repository: str) -> str | None:
        import urllib.request

        auth_url = f"https://auth.{registry_url.replace('https://', '')}/token?scope=repository:{repository}:pull&service=registry.docker.io"
        try:
            with urllib.request.urlopen(auth_url, timeout=30) as response:
                token_data = json.loads(response.read())
                return token_data.get("token")
        except Exception:
            return None

    def _make_request(self, url: str, token: str | None = None, accept: str = "*/*") -> bytes:
        import urllib.request

        headers = {"Accept": accept}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()

    def _extract_layer(self, layer_data: bytes, dest: Path) -> None:
        try:
            if tarfile.is_tarfile(io.BytesIO(layer_data)):
                with tarfile.open(fileobj=io.BytesIO(layer_data), "r:*") as tf:
                    tf.extractall(dest)
        except Exception:
            pass

    def _find_template_root(self, extracted_path: Path) -> Path:
        items = list(extracted_path.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return extracted_path


def get_fetcher(url: str) -> TemplateFetcher | None:
    """Get the appropriate fetcher for the given URL.

    The order of checking is important:
    1. First check if it's an OCI URL (most specific)
    2. Then check if it's a Git URL (including http git URLs)
    3. Finally check if it's a generic HTTP(S) URL

    Args:
        url: URL to fetch template from.

    Returns:
        Fetcher instance that can handle the URL, or None if no fetcher matches.
    """
    oci_fetcher = OciFetcher()
    if oci_fetcher.can_handle(url):
        return oci_fetcher

    git_fetcher = GitFetcher()
    if git_fetcher.can_handle(url):
        return git_fetcher

    http_fetcher = HttpFetcher()
    if http_fetcher.can_handle(url):
        return http_fetcher

    return None


def is_remote_url(url: str) -> bool:
    """Check if the URL is a remote URL (git, http, oci)."""
    return get_fetcher(url) is not None
