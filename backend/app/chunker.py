from dataclasses import dataclass
from pathlib import Path

import tree_sitter
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    "target",
    ".idea",
    ".vscode",
}

IGNORED_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "composer.lock",
}

TEXT_FALLBACK_EXTENSIONS = {
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".md": "markdown",
    ".css": "css",
    ".html": "html",
}

MAX_CHUNK_CHARS = 3500
FALLBACK_WINDOW_LINES = 80
FALLBACK_OVERLAP_LINES = 15


@dataclass(frozen=True)
class ParsedChunk:
    file_path: str
    symbol_name: str
    symbol_type: str
    language: str
    start_line: int
    end_line: int
    content: str


def _build_parsers() -> dict[str, tuple[str, tree_sitter.Parser]]:
    py_lang = tree_sitter.Language(tree_sitter_python.language())
    js_lang = tree_sitter.Language(tree_sitter_javascript.language())
    ts_lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
    tsx_lang = tree_sitter.Language(tree_sitter_typescript.language_tsx())

    py_parser = tree_sitter.Parser(py_lang)
    js_parser = tree_sitter.Parser(js_lang)
    ts_parser = tree_sitter.Parser(ts_lang)
    tsx_parser = tree_sitter.Parser(tsx_lang)

    return {
        ".py": ("python", py_parser),
        ".js": ("javascript", js_parser),
        ".jsx": ("javascript", js_parser),
        ".mjs": ("javascript", js_parser),
        ".cjs": ("javascript", js_parser),
        ".ts": ("typescript", ts_parser),
        ".tsx": ("tsx", tsx_parser),
    }


_PARSERS = _build_parsers()


def _node_text(source_bytes: bytes, node: tree_sitter.Node) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _extract_identifier(source_bytes: bytes, node: tree_sitter.Node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(source_bytes, name_node)

    for child in node.children:
        if child.type in {"identifier", "property_identifier", "type_identifier"}:
            return _node_text(source_bytes, child)
        if child.type == "variable_declarator":
            inner = child.child_by_field_name("name")
            if inner is not None:
                return _node_text(source_bytes, inner)
    return "<anonymous>"


def _split_oversized_chunk(
    *,
    file_path: str,
    symbol_name: str,
    symbol_type: str,
    language: str,
    start_line: int,
    text: str,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[ParsedChunk]:
    if len(text) <= max_chars:
        end_line = start_line + max(0, text.count("\n"))
        return [
            ParsedChunk(
                file_path=file_path,
                symbol_name=symbol_name,
                symbol_type=symbol_type,
                language=language,
                start_line=start_line,
                end_line=end_line,
                content=text,
            )
        ]

    lines = text.splitlines()
    chunks: list[ParsedChunk] = []
    idx = 0
    part = 1
    while idx < len(lines):
        buf: list[str] = []
        char_count = 0
        chunk_start = start_line + idx
        while idx < len(lines):
            candidate = lines[idx]
            if buf and char_count + len(candidate) + 1 > max_chars:
                break
            buf.append(candidate)
            char_count += len(candidate) + 1
            idx += 1
        chunk_end = chunk_start + len(buf) - 1
        chunks.append(
            ParsedChunk(
                file_path=file_path,
                symbol_name=f"{symbol_name}#part{part}",
                symbol_type=symbol_type,
                language=language,
                start_line=chunk_start,
                end_line=chunk_end,
                content="\n".join(buf),
            )
        )
        part += 1
    return chunks


def _extract_python_chunks(file_path: str, source_bytes: bytes, root: tree_sitter.Node) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []

    def visit(node: tree_sitter.Node, parent_class: str | None = None) -> None:
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            if definition is not None:
                name = _extract_identifier(source_bytes, definition)
                full_name = f"{parent_class}.{name}" if parent_class else name
                sym_type = "class" if definition.type == "class_definition" else "function"
                text = _node_text(source_bytes, node)
                if definition.type == "class_definition" and len(text) > MAX_CHUNK_CHARS:
                    body = definition.child_by_field_name("body")
                    if body is not None:
                        for child in body.children:
                            visit(child, parent_class=name)
                        return
                chunks.extend(
                    _split_oversized_chunk(
                        file_path=file_path,
                        symbol_name=full_name,
                        symbol_type=sym_type,
                        language="python",
                        start_line=node.start_point[0] + 1,
                        text=text,
                    )
                )
            return

        if node.type in {"function_definition", "class_definition"}:
            name = _extract_identifier(source_bytes, node)
            full_name = f"{parent_class}.{name}" if parent_class else name
            sym_type = "class" if node.type == "class_definition" else ("method" if parent_class else "function")
            text = _node_text(source_bytes, node)

            if node.type == "class_definition" and len(text) > MAX_CHUNK_CHARS:
                body = node.child_by_field_name("body")
                if body is not None:
                    for child in body.children:
                        visit(child, parent_class=name)
                    return

            chunks.extend(
                _split_oversized_chunk(
                    file_path=file_path,
                    symbol_name=full_name,
                    symbol_type=sym_type,
                    language="python",
                    start_line=node.start_point[0] + 1,
                    text=text,
                )
            )
            return

        for child in node.children:
            visit(child, parent_class=parent_class)

    visit(root)
    return chunks


def _extract_js_ts_chunks(
    file_path: str,
    language: str,
    source_bytes: bytes,
    root: tree_sitter.Node,
) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []

    def has_function_initializer(node: tree_sitter.Node) -> bool:
        for child in node.children:
            if child.type == "variable_declarator":
                val = child.child_by_field_name("value")
                if val is not None and val.type in {"arrow_function", "function_expression", "function"}:
                    return True
        return False

    def visit(node: tree_sitter.Node, parent_class: str | None = None) -> None:
        if node.type == "export_statement":
            decl = node.child_by_field_name("declaration")
            if decl is not None and decl.type in {
                "function_declaration",
                "class_declaration",
                "interface_declaration",
                "type_alias_declaration",
                "lexical_declaration",
                "variable_statement",
            }:
                if decl.type in {"lexical_declaration", "variable_statement"} and not has_function_initializer(decl):
                    return
                name = _extract_identifier(source_bytes, decl)
                sym_type = decl.type.replace("_declaration", "").replace("_statement", "")
                text = _node_text(source_bytes, node)
                if decl.type == "class_declaration" and len(text) > MAX_CHUNK_CHARS:
                    body = decl.child_by_field_name("body")
                    if body is not None:
                        for child in body.children:
                            visit(child, parent_class=name)
                        return
                chunks.extend(
                    _split_oversized_chunk(
                        file_path=file_path,
                        symbol_name=name,
                        symbol_type=sym_type,
                        language=language,
                        start_line=node.start_point[0] + 1,
                        text=text,
                    )
                )
                return

        if node.type in {
            "function_declaration",
            "class_declaration",
            "method_definition",
            "interface_declaration",
            "type_alias_declaration",
        }:
            name = _extract_identifier(source_bytes, node)
            full_name = f"{parent_class}.{name}" if parent_class else name
            sym_type = node.type.replace("_declaration", "").replace("_definition", "")
            text = _node_text(source_bytes, node)

            if node.type == "class_declaration" and len(text) > MAX_CHUNK_CHARS:
                body = node.child_by_field_name("body")
                if body is not None:
                    for child in body.children:
                        visit(child, parent_class=name)
                    return

            chunks.extend(
                _split_oversized_chunk(
                    file_path=file_path,
                    symbol_name=full_name,
                    symbol_type=sym_type,
                    language=language,
                    start_line=node.start_point[0] + 1,
                    text=text,
                )
            )
            return

        if node.type in {"lexical_declaration", "variable_statement"} and has_function_initializer(node):
            name = _extract_identifier(source_bytes, node)
            chunks.extend(
                _split_oversized_chunk(
                    file_path=file_path,
                    symbol_name=name,
                    symbol_type="function",
                    language=language,
                    start_line=node.start_point[0] + 1,
                    text=_node_text(source_bytes, node),
                )
            )
            return

        for child in node.children:
            visit(child, parent_class=parent_class)

    visit(root)
    return chunks


def _fallback_line_chunks(file_path: str, language: str, text: str) -> list[ParsedChunk]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[ParsedChunk] = []
    step = max(1, FALLBACK_WINDOW_LINES - FALLBACK_OVERLAP_LINES)
    for idx in range(0, len(lines), step):
        window = lines[idx : idx + FALLBACK_WINDOW_LINES]
        content = "\n".join(window).strip()
        if not content:
            continue
        start_line = idx + 1
        end_line = idx + len(window)
        chunks.extend(
            _split_oversized_chunk(
                file_path=file_path,
                symbol_name=f"{Path(file_path).name}:{start_line}-{end_line}",
                symbol_type="block",
                language=language,
                start_line=start_line,
                text=content,
            )
        )
        if idx + FALLBACK_WINDOW_LINES >= len(lines):
            break
    return chunks


def chunk_source_text(file_path: str, source_text: str) -> list[ParsedChunk]:
    """Chunk a single file using Tree-sitter AST when supported, or line-window fallback."""
    if not source_text.strip():
        return []

    suffix = Path(file_path).suffix.lower()
    filename = Path(file_path).name

    if suffix in _PARSERS:
        language, parser = _PARSERS[suffix]
        source_bytes = source_text.encode("utf-8", errors="replace")
        tree = parser.parse(source_bytes)
        if language == "python":
            ast_chunks = _extract_python_chunks(file_path, source_bytes, tree.root_node)
        else:
            ast_chunks = _extract_js_ts_chunks(file_path, language, source_bytes, tree.root_node)
        if ast_chunks:
            return ast_chunks
        return _fallback_line_chunks(file_path, language, source_text)

    if filename == "Dockerfile" or filename.startswith("Dockerfile."):
        return _fallback_line_chunks(file_path, "dockerfile", source_text)

    if suffix in TEXT_FALLBACK_EXTENSIONS:
        return _fallback_line_chunks(file_path, TEXT_FALLBACK_EXTENSIONS[suffix], source_text)

    return []


def is_supported_source_path(rel_path: str) -> bool:
    """Return True if a repository-relative path is an indexable non-ignored source/config file."""
    path = Path(rel_path)
    if any(part in IGNORED_DIRS for part in path.parts):
        return False
    if path.name in IGNORED_FILES:
        return False
    lower_name = path.name.lower()
    if lower_name.endswith(".min.js") or lower_name.endswith(".min.css") or lower_name.endswith(".map"):
        return False
    suffix = path.suffix.lower()
    return (
        suffix in _PARSERS
        or suffix in TEXT_FALLBACK_EXTENSIONS
        or path.name.startswith("Dockerfile")
    )


def source_path_priority(rel_path: str) -> tuple[int, int, str]:
    """Rank repository files so core source code & tests are indexed before docs/styles."""
    path = Path(rel_path)
    suffix = path.suffix.lower()
    lower = rel_path.lower()

    if suffix in _PARSERS or suffix in {".go", ".rs", ".java", ".kt", ".rb", ".php"}:
        tier = 0
    elif (
        suffix in {".sql", ".sh", ".yaml", ".yml", ".toml"}
        or path.name.startswith("Dockerfile")
        or path.name in {"package.json", "pyproject.toml"}
    ):
        tier = 1
    else:
        tier = 2

    is_test = 0 if ("test" in lower or "spec" in lower) else 1
    return (tier, is_test, rel_path)


def chunk_repository_directory(
    repo_dir: Path,
    *,
    max_files: int = 500,
    max_file_bytes: int = 262144,
) -> list[ParsedChunk]:
    """Walk an ephemeral cloned repository directory and return AST-parsed code chunks."""
    all_chunks: list[ParsedChunk] = []
    processed_files = 0

    for path in sorted(repo_dir.rglob("*")):
        if processed_files >= max_files:
            break
        if path.is_dir():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(repo_dir).parts):
            continue
        if path.name in IGNORED_FILES:
            continue

        rel_path = path.relative_to(repo_dir).as_posix()
        suffix = path.suffix.lower()
        if suffix not in _PARSERS and suffix not in TEXT_FALLBACK_EXTENSIONS and not path.name.startswith("Dockerfile"):
            continue

        try:
            if path.stat().st_size > max_file_bytes:
                continue
            raw = path.read_bytes()
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue

        file_chunks = chunk_source_text(rel_path, text)
        if file_chunks:
            all_chunks.extend(file_chunks)
            processed_files += 1

    return all_chunks
