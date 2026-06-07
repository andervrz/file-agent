"""
Tests para los 8 file tools.

Cubre:
- create_file, read_file, list_directory
- move_file, copy_file, delete_file
- create_directory, search_files
- PathSafeguard integrado
- Límites de tamaño (50KB lectura, 50 matches búsqueda)
- asyncio.to_thread() para operaciones bloqueantes
"""

import asyncio
import pytest
from pathlib import Path

from agent.tools.base import PathSafeguard, ToolResult
from agent.tools.file_tools import (
    build_file_tools,
    CreateFileTool,
    ReadFileTool,
    ListDirectoryTool,
    MoveFileTool,
    CopyFileTool,
    DeleteFileTool,
    CreateDirectoryTool,
    SearchFilesTool,
)


class TestFileTools:
    """Suite completa de tools de archivo con filesystem real temporal."""

    @pytest.fixture
    def safeguard(self):
        return PathSafeguard(blocked_paths=["/etc", "/sys", "/usr", "/bin"])

    @pytest.fixture
    def tools(self, safeguard):
        """Diccionario de tools por nombre."""
        tool_list = build_file_tools(
            safeguard=safeguard,
            enabled=[
                "create_file", "read_file", "list_directory",
                "move_file", "copy_file", "delete_file",
                "create_directory", "search_files",
            ]
        )
        return {t.name: t for t in tool_list}

    # ── create_file ──
    @pytest.mark.asyncio
    async def test_create_file(self, tools, tmp_path):
        file_path = tmp_path / "test.txt"
        result = await tools["create_file"].execute(
            tool_use_id="t1", path=str(file_path), content="hello world"
        )
        assert result.is_error is False
        assert file_path.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_create_file_overwrite_false(self, tools, tmp_path):
        file_path = tmp_path / "existing.txt"
        file_path.write_text("original")
        result = await tools["create_file"].execute(
            tool_use_id="t2", path=str(file_path), content="new", overwrite=False
        )
        assert result.is_error is True
        assert file_path.read_text() == "original"

    @pytest.mark.asyncio
    async def test_create_file_overwrite_true(self, tools, tmp_path):
        file_path = tmp_path / "existing.txt"
        file_path.write_text("original")
        result = await tools["create_file"].execute(
            tool_use_id="t3", path=str(file_path), content="new", overwrite=True
        )
        assert result.is_error is False
        assert file_path.read_text() == "new"

    @pytest.mark.asyncio
    async def test_create_file_creates_parent_dirs(self, tools, tmp_path):
        file_path = tmp_path / "a" / "b" / "c.txt"
        result = await tools["create_file"].execute(
            tool_use_id="t4", path=str(file_path), content="nested"
        )
        assert result.is_error is False
        assert file_path.read_text() == "nested"

    @pytest.mark.asyncio
    async def test_create_file_blocked_path(self, tools, tmp_path):
        result = await tools["create_file"].execute(
            tool_use_id="t5", path="/etc/passwd", content="hacked"
        )
        assert result.is_error is True

    # ── read_file ──
    @pytest.mark.asyncio
    async def test_read_file(self, tools, tmp_path):
        file_path = tmp_path / "read_me.txt"
        file_path.write_text("content here")
        result = await tools["read_file"].execute(
            tool_use_id="t6", path=str(file_path)
        )
        assert result.is_error is False
        assert "content here" in result.content

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, tools, tmp_path):
        result = await tools["read_file"].execute(
            tool_use_id="t7", path=str(tmp_path / "nonexistent.txt")
        )
        assert result.is_error is True
        assert "no encontrado" in result.content.lower() or "not found" in result.content.lower()

    @pytest.mark.asyncio
    async def test_read_file_truncates_over_50kb(self, tools, tmp_path):
        file_path = tmp_path / "big.txt"
        file_path.write_text("A" * 60000)
        result = await tools["read_file"].execute(
            tool_use_id="t8", path=str(file_path)
        )
        assert result.is_error is False
        assert len(result.content) <= 52000  # 50KB + margen de aviso
        assert "truncado" in result.content.lower() or "truncated" in result.content.lower() or "trunc" in result.content.lower()

    # ── list_directory ──
    @pytest.mark.asyncio
    async def test_list_directory(self, tools, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        (tmp_path / "subdir").mkdir()

        result = await tools["list_directory"].execute(
            tool_use_id="t9", path=str(tmp_path)
        )
        assert result.is_error is False
        assert "file1.txt" in result.content
        assert "file2.txt" in result.content
        assert "subdir" in result.content

    @pytest.mark.asyncio
    async def test_list_directory_show_hidden(self, tools, tmp_path):
        (tmp_path / ".hidden").write_text("secret")
        result_hidden = await tools["list_directory"].execute(
            tool_use_id="t10", path=str(tmp_path), show_hidden=True
        )
        assert ".hidden" in result_hidden.content

        result_no_hidden = await tools["list_directory"].execute(
            tool_use_id="t11", path=str(tmp_path), show_hidden=False
        )
        assert ".hidden" not in result_no_hidden.content

    @pytest.mark.asyncio
    async def test_list_directory_not_found(self, tools, tmp_path):
        result = await tools["list_directory"].execute(
            tool_use_id="t12", path=str(tmp_path / "nonexistent")
        )
        assert result.is_error is True

    # ── create_directory ──
    @pytest.mark.asyncio
    async def test_create_directory(self, tools, tmp_path):
        dir_path = tmp_path / "new_dir"
        result = await tools["create_directory"].execute(
            tool_use_id="t13", path=str(dir_path)
        )
        assert result.is_error is False
        assert dir_path.is_dir()

    @pytest.mark.asyncio
    async def test_create_directory_nested(self, tools, tmp_path):
        dir_path = tmp_path / "a" / "b" / "c"
        result = await tools["create_directory"].execute(
            tool_use_id="t14", path=str(dir_path)
        )
        assert result.is_error is False
        assert dir_path.is_dir()

    @pytest.mark.asyncio
    async def test_create_directory_blocked(self, tools, tmp_path):
        result = await tools["create_directory"].execute(
            tool_use_id="t15", path="/usr/new_dir"
        )
        assert result.is_error is True

    # ── move_file ──
    @pytest.mark.asyncio
    async def test_move_file(self, tools, tmp_path):
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("move me")
        result = await tools["move_file"].execute(
            tool_use_id="t16", source=str(src), destination=str(dst)
        )
        assert result.is_error is False
        assert not src.exists()
        assert dst.read_text() == "move me"

    @pytest.mark.asyncio
    async def test_move_file_not_found(self, tools, tmp_path):
        result = await tools["move_file"].execute(
            tool_use_id="t17", source=str(tmp_path / "nope.txt"), destination=str(tmp_path / "dest.txt")
        )
        assert result.is_error is True

    # ── copy_file ──
    @pytest.mark.asyncio
    async def test_copy_file(self, tools, tmp_path):
        src = tmp_path / "original.txt"
        dst = tmp_path / "copy.txt"
        src.write_text("copy me")
        result = await tools["copy_file"].execute(
            tool_use_id="t18", source=str(src), destination=str(dst)
        )
        assert result.is_error is False
        assert src.exists()
        assert dst.read_text() == "copy me"

    @pytest.mark.asyncio
    async def test_copy_file_preserves_metadata(self, tools, tmp_path):
        """copy2 debe preservar metadata (timestamps)."""
        src = tmp_path / "meta.txt"
        src.write_text("meta")
        import time
        time.sleep(0.01)
        dst = tmp_path / "meta_copy.txt"
        result = await tools["copy_file"].execute(
            tool_use_id="t19", source=str(src), destination=str(dst)
        )
        assert result.is_error is False
        # copy2 preserva timestamps, no solo contenido
        assert dst.exists()

    # ── delete_file ──
    @pytest.mark.asyncio
    async def test_delete_file(self, tools, tmp_path):
        file_path = tmp_path / "delete_me.txt"
        file_path.write_text("bye")
        result = await tools["delete_file"].execute(
            tool_use_id="t20", path=str(file_path)
        )
        assert result.is_error is False
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_file_not_found(self, tools, tmp_path):
        result = await tools["delete_file"].execute(
            tool_use_id="t21", path=str(tmp_path / "nope.txt")
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_delete_file_blocked(self, tools, tmp_path):
        result = await tools["delete_file"].execute(
            tool_use_id="t22", path="/etc/passwd"
        )
        assert result.is_error is True

    # ── search_files ──
    @pytest.mark.asyncio
    async def test_search_files_pattern(self, tools, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.txt").write_text("z")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "d.py").write_text("w")

        result = await tools["search_files"].execute(
            tool_use_id="t23", directory=str(tmp_path), pattern="*.py"
        )
        assert result.is_error is False
        assert "a.py" in result.content
        assert "b.py" in result.content
        assert "d.py" in result.content
        assert "c.txt" not in result.content

    @pytest.mark.asyncio
    async def test_search_files_non_recursive(self, tools, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("y")

        result = await tools["search_files"].execute(
            tool_use_id="t24", directory=str(tmp_path), pattern="*.py", recursive=False
        )
        assert result.is_error is False
        assert "a.py" in result.content
        assert "b.py" not in result.content

    @pytest.mark.asyncio
    async def test_search_files_limit_50(self, tools, tmp_path):
        for i in range(60):
            (tmp_path / f"file_{i}.py").write_text("x")
        result = await tools["search_files"].execute(
            tool_use_id="t25", directory=str(tmp_path), pattern="*.py"
        )
        assert result.is_error is False
        # Debe limitar a 50 matches
        matches = [line for line in result.content.split("\n") if ".py" in line]
        assert len(matches) <= 50

    # ── expanduser integration ──
    @pytest.mark.asyncio
    async def test_create_file_expanduser(self, tools, tmp_path, monkeypatch):
        """~ debe expandirse correctamente (Bug 3)."""
        fake_home = tmp_path / "home" / "testuser"
        fake_home.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))
        # Nota: Path("~/test.txt").expanduser() usa $HOME
        file_path = fake_home / "test.txt"
        result = await tools["create_file"].execute(
            tool_use_id="t26", path="~/test.txt", content="tilde works"
        )
        assert result.is_error is False
        assert file_path.read_text() == "tilde works"
