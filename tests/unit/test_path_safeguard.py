"""
Tests para PathSafeguard.

Cubre:
- expanduser() resuelve ~ correctamente
- paths bloqueados son rechazados
- paths válidos pasan la validación
- paths relativos se resuelven a absolutos
"""

import pytest
from pathlib import Path
from agent.tools.base import PathSafeguard


class TestPathSafeguard:
    """Suite de seguridad de paths — crítico para operaciones de filesystem."""

    @pytest.fixture
    def safeguard(self):
        """Safeguard con paths bloqueados de producción."""
        return PathSafeguard(
            blocked_paths=[
                "/etc",
                "/sys",
                "/usr",
                "/bin",
                "/sbin",
                "/proc",
                "/dev",
            ]
        )

    # ── expanduser() ──
    def test_expanduser_tilde(self, safeguard):
        """~ debe expandirse al home del usuario antes de validar."""
        result = safeguard.validate("~/Documents")
        assert str(result).startswith("/")
        assert "~" not in str(result)
        assert result.name == "Documents"

    def test_expanduser_tilde_downloads(self, safeguard):
        """~/Downloads debe resolverse fuera del directorio del proyecto."""
        result = safeguard.validate("~/Downloads")
        assert str(result).startswith("/home/")
        assert result.name == "Downloads"

    def test_no_expanduser_relative_path(self, safeguard, tmp_path):
        """Paths relativos sin ~ se resuelven contra CWD."""
        result = safeguard.validate(".")
        assert result.is_absolute()
        assert result == Path(".").resolve()

    # ── paths bloqueados ──
    def test_blocked_etc(self, safeguard):
        """/etc debe ser bloqueado."""
        with pytest.raises(PermissionError) as exc:
            safeguard.validate("/etc/passwd")
        assert "bloqueado" in str(exc.value).lower() or "blocked" in str(exc.value).lower()

    def test_blocked_usr(self, safeguard):
        """/usr debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/usr/local/bin")

    def test_blocked_proc(self, safeguard):
        """/proc debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/proc/1/status")

    def test_blocked_bin(self, safeguard):
        """/bin debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/bin/ls")

    def test_blocked_sbin(self, safeguard):
        """/sbin debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/sbin/init")

    def test_blocked_dev(self, safeguard):
        """/dev debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/dev/sda")

    def test_blocked_sys(self, safeguard):
        """/sys debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/sys/kernel")

    # ── paths válidos ──
    def test_valid_home_path(self, safeguard):
        """Paths bajo /home/ deben ser válidos."""
        result = safeguard.validate("/home/ANDERVRZ/Documents")
        assert result.is_absolute()
        assert result == Path("/home/ANDERVRZ/Documents")

    def test_valid_tmp_path(self, safeguard):
        """/tmp debe ser válido."""
        result = safeguard.validate("/tmp/test_file")
        assert result.is_absolute()

    def test_valid_relative_to_home(self, safeguard):
        """Paths relativos que resuelven a home deben pasar."""
        result = safeguard.validate("./file.txt")
        assert result.is_absolute()

    # ── edge cases ──
    def test_blocked_path_with_symlink_traversal(self, safeguard):
        """Intento de symlink traversal hacia /etc debe ser bloqueado."""
        with pytest.raises(PermissionError):
            safeguard.validate("/tmp/fake/../../etc/passwd")

    def test_path_is_path_object(self, safeguard):
        """validate() debe aceptar Path objects además de strings."""
        result = safeguard.validate(Path("/tmp/foo"))
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_blocked_path_parent_is_blocked(self, safeguard):
        """Un path cuyo padre resuelto está bloqueado debe rechazarse."""
        with pytest.raises(PermissionError):
            safeguard.validate("/etc/")
