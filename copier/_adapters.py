"""IO adapters for separating pure computation from side effects.

This module provides adapter interfaces for file system operations, Git operations,
and task execution. This separation allows:
- The main rendering logic to be pure and testable
- Different implementations for real execution vs. pretend mode
- Easier preview/review of what changes will be made
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import warnings
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from plumbum import ProcessExecutionError
from plumbum.machines import local

from ._vcs import get_git, is_git_available


@dataclass
class FileRenderResult:
    """Result of rendering a file (pure computation result)."""
    dst_relpath: Path
    new_content: bytes
    src_mode: int
    is_symlink: bool = False
    symlink_target: Path | None = None
    is_dir: bool = False

    @property
    def expected_contents(self) -> bytes | Path:
        """Get the expected contents for _render_allowed comparison."""
        if self.is_symlink:
            assert self.symlink_target is not None, "symlink_target must be set for symlinks"
            return self.symlink_target
        return self.new_content


class FileSystemAdapter(ABC):
    """Abstract base class for file system operations."""

    @abstractmethod
    def read_bytes(self, path: Path) -> bytes:
        """Read bytes from a file."""
        ...

    @abstractmethod
    def readlink(self, path: Path) -> Path:
        """Read the target of a symbolic link."""
        ...

    @abstractmethod
    def is_symlink(self, path: Path) -> bool:
        """Check if a path is a symbolic link."""
        ...

    @abstractmethod
    def is_dir(self, path: Path, follow_symlinks: bool = True) -> bool:
        """Check if a path is a directory."""
        ...

    @abstractmethod
    def is_file(self, path: Path) -> bool:
        """Check if a path is a file."""
        ...

    @abstractmethod
    def exists(self, path: Path) -> bool:
        """Check if a path exists."""
        ...

    @abstractmethod
    def stat(self, path: Path) -> os.stat_result:
        """Get file statistics."""
        ...

    @abstractmethod
    def lstat(self, path: Path) -> os.stat_result:
        """Get file statistics without following symlinks."""
        ...

    @abstractmethod
    def write_bytes(self, path: Path, content: bytes) -> None:
        """Write bytes to a file."""
        ...

    @abstractmethod
    def mkdir(self, path: Path, parents: bool = True, exist_ok: bool = True) -> None:
        """Create a directory."""
        ...

    @abstractmethod
    def unlink(self, path: Path) -> None:
        """Remove a file or symbolic link."""
        ...

    @abstractmethod
    def rmdir(self, path: Path) -> None:
        """Remove an empty directory."""
        ...

    @abstractmethod
    def chmod(self, path: Path, mode: int) -> None:
        """Change file permissions."""
        ...

    @abstractmethod
    def lchmod(self, path: Path, mode: int) -> None:
        """Change symlink permissions (only supported on macOS)."""
        ...

    @abstractmethod
    def symlink_to(self, path: Path, target: Path) -> None:
        """Create a symbolic link."""
        ...

    @abstractmethod
    def glob(self, path: Path, pattern: str) -> list[Path]:
        """Find all paths matching a pattern."""
        ...


class RealFileSystemAdapter(FileSystemAdapter):
    """Real file system implementation using standard library functions."""

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def readlink(self, path: Path) -> Path:
        return path.readlink()

    def is_symlink(self, path: Path) -> bool:
        return path.is_symlink()

    def is_dir(self, path: Path, follow_symlinks: bool = True) -> bool:
        return path.is_dir(follow_symlinks=follow_symlinks)

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def exists(self, path: Path) -> bool:
        return path.exists()

    def stat(self, path: Path) -> os.stat_result:
        return path.stat()

    def lstat(self, path: Path) -> os.stat_result:
        return path.lstat()

    def write_bytes(self, path: Path, content: bytes) -> None:
        path.write_bytes(content)

    def mkdir(self, path: Path, parents: bool = True, exist_ok: bool = True) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def unlink(self, path: Path) -> None:
        path.unlink()

    def rmdir(self, path: Path) -> None:
        path.rmdir()

    def chmod(self, path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except PermissionError:
            dst_mode = path.stat().st_mode
            warnings.warn(
                f"Path permissions for {path} cannot be changed from "
                f"{stat.filemode(dst_mode)} to {stat.filemode(mode)}",
                stacklevel=2,
            )

    def lchmod(self, path: Path, mode: int) -> None:
        if sys.platform == "darwin":
            path.lchmod(mode)

    def symlink_to(self, path: Path, target: Path) -> None:
        path.symlink_to(target)

    def glob(self, path: Path, pattern: str) -> list[Path]:
        return list(path.glob(pattern))


class GitAdapter(ABC):
    """Abstract base class for Git operations."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if git is available."""
        ...

    @abstractmethod
    def sync_executable_bit(self, subproject_root: Path, dst_relpath: Path, src_mode: int) -> None:
        """Sync the executable bit to the git index."""
        ...


class RealGitAdapter(GitAdapter):
    """Real Git implementation using the git command."""

    def is_available(self) -> bool:
        return is_git_available()

    def sync_executable_bit(self, subproject_root: Path, dst_relpath: Path, src_mode: int) -> None:
        git = get_git(context_dir=subproject_root)
        try:
            file_mode_setting = git(
                "config", "--type=bool", "--get", "core.fileMode"
            ).strip()
        except ProcessExecutionError:
            return
        if file_mode_setting != "false":
            return
        try:
            result = git("ls-files", "--stage", "--", str(dst_relpath)).strip()
        except ProcessExecutionError:
            return
        if not result:
            return
        meta = result.split("\t", 1)[0].split()
        current_index_mode = int(meta[0], 8)
        current_index_sha = meta[1]
        desired_executable = bool(src_mode & 0o111)
        current_executable = bool(current_index_mode & 0o111)
        if desired_executable == current_executable:
            return
        new_mode = "100755" if desired_executable else "100644"
        try:
            git(
                "update-index",
                "--cacheinfo",
                f"{new_mode},{current_index_sha},{dst_relpath}",
            )
        except (OSError, ProcessExecutionError):
            pass


class TaskExecutor(ABC):
    """Abstract base class for executing tasks (subprocesses)."""

    @abstractmethod
    def execute(
        self,
        cmd: str | Sequence[str],
        working_directory: Path,
        env: dict[str, str] | None = None,
        use_shell: bool = False,
    ) -> int:
        """Execute a task and return the exit code."""
        ...


class RealTaskExecutor(TaskExecutor):
    """Real task executor using subprocess."""

    def execute(
        self,
        cmd: str | Sequence[str],
        working_directory: Path,
        env: dict[str, str] | None = None,
        use_shell: bool = False,
    ) -> int:
        with local.cwd(working_directory), local.env(**(env or {})):
            process = subprocess.run(cmd, shell=use_shell, env=local.env)
            return process.returncode


@dataclass
class IOAdapters:
    """Container for all IO adapters."""
    fs: FileSystemAdapter
    git: GitAdapter
    tasks: TaskExecutor

    @classmethod
    def real(cls) -> IOAdapters:
        """Create IO adapters for real execution."""
        return cls(
            fs=RealFileSystemAdapter(),
            git=RealGitAdapter(),
            tasks=RealTaskExecutor(),
        )
