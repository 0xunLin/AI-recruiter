from pathlib import Path

from app.chunker import chunk_repository_directory, chunk_source_text


def test_python_ast_chunking_preserves_functions_and_decorators() -> None:
    source = '''
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health_check():
    return {"ok": True}

class TenantService:
    def verify(self, company_id: str) -> bool:
        return bool(company_id)
'''
    chunks = chunk_source_text("app/routes.py", source)
    symbols = {(c.symbol_name, c.symbol_type) for c in chunks}

    assert ("health_check", "function") in symbols
    assert ("TenantService", "class") in symbols
    health_chunk = next(c for c in chunks if c.symbol_name == "health_check")
    assert '@router.get("/health")' in health_chunk.content
    assert health_chunk.language == "python"


def test_typescript_ast_chunking_extracts_exports_and_arrow_functions() -> None:
    source = '''
export interface Candidate {
  id: string;
  name: string;
}

export const formatScore = (score: number): string => {
  return `${score.toFixed(2)} / 5`;
};

export function evaluateRepo(url: string): boolean {
  return url.startsWith("https://github.com/");
}
'''
    chunks = chunk_source_text("src/utils.ts", source)
    names = {c.symbol_name for c in chunks}
    assert "Candidate" in names
    assert "formatScore" in names
    assert "evaluateRepo" in names


def test_directory_walker_skips_ignored_dirs_and_lockfiles(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "service.py").write_text("def run():\n    return 42\n")

    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("function ignored() {}\n")

    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}')

    chunks = chunk_repository_directory(tmp_path)
    paths = {c.file_path for c in chunks}
    assert "app/service.py" in paths
    assert "node_modules/pkg/index.js" not in paths
    assert "package-lock.json" not in paths
