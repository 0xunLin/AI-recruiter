import os
from dataclasses import dataclass
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

# 1. Initialize Language Grammars once at module load time
PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjavascript.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())

# Map file extensions to their corresponding Tree-sitter Language
EXTENSION_TO_LANGUAGE = {
    ".py": ("python", PY_LANGUAGE),
    ".js": ("javascript", JS_LANGUAGE),
    ".jsx": ("javascript", JS_LANGUAGE),
    ".ts": ("typescript", TS_LANGUAGE),
    ".tsx": ("tsx", TSX_LANGUAGE),
}

# Define which AST node types represent meaningful, self-contained units of logic
TARGET_NODE_TYPES = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition", "lexical_declaration"},
    "typescript": {"function_declaration", "class_declaration", "method_definition", "interface_declaration"},
    "tsx": {"function_declaration", "class_declaration", "method_definition", "interface_declaration"},
}

# Directories and noisy files we must never waste tokens embedding
IGNORED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next"}

@dataclass
class ExtractedChunk:
    """Data structure representing a single semantic piece of code ready for embedding."""
    file_path: str
    content: str
    start_line: int
    end_line: int
    node_type: str

def _walk_and_extract(node, source_bytes: bytes, file_path: str, target_types: set[str], chunks: list[ExtractedChunk]):
    """
    Depth-first traversal of the syntax tree.
    When we hit a target node (e.g., a function or class), we extract it as a single chunk
    and stop recursing into its children so we don't duplicate inner helper functions.
    """
    if node.type in target_types:
        # Tree-sitter works on raw bytes, so we slice the byte array and decode back to UTF-8 string
        raw_code = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        start_line = node.start_point[0] + 1  # Convert 0-indexed row to 1-indexed line number
        end_line = node.end_point[0] + 1

        # Prepend file and line metadata directly into the chunk for the LLM Evaluator's evidence
        formatted_content = (
            f"# File: {file_path} (Lines {start_line}-{end_line}) | Type: {node.type}\n"
            f"{raw_code}"
        )

        chunks.append(
            ExtractedChunk(
                file_path=file_path,
                content=formatted_content,
                start_line=start_line,
                end_line=end_line,
                node_type=node.type,
            )
        )
        return  # Stop recursing into children to prevent duplicate sub-chunks

    # Otherwise, keep walking down the tree's children
    for child in node.children:
        _walk_and_extract(child, source_bytes, file_path, target_types, chunks)

# Replace parse_file in app/chunker.py with this:
def parse_file(abs_file_path: str, rel_file_path: str) -> list[ExtractedChunk]:
    """
    Parses a single source file into semantic AST chunks:
    1. Extracts all functions/classes/methods as individual AST chunks.
    2. Groups any remaining top-level module statements (configs, constants, setup calls)
       into a 'module_globals' chunk so mixed-scope files never lose top-level logic.
    """
    _, ext = os.path.splitext(rel_file_path)
    ext = ext.lower()

    if ext not in EXTENSION_TO_LANGUAGE:
        return []

    lang_name, language_obj = EXTENSION_TO_LANGUAGE[ext]

    try:
        with open(abs_file_path, "rb") as f:
            source_bytes = f.read()
    except OSError:
        return []

    if not source_bytes.strip() or len(source_bytes) > 100_000:
        return []

    parser = Parser(language_obj)
    tree = parser.parse(source_bytes)

    chunks: list[ExtractedChunk] = []
    target_types = TARGET_NODE_TYPES[lang_name]

    # 1. Extract all function/class definitions
    _walk_and_extract(tree.root_node, source_bytes, rel_file_path, target_types, chunks)

    # 2. Collect remaining top-level statements (outside functions/classes)
    top_level_lines: list[str] = []
    for child in tree.root_node.children:
        if child.type not in target_types:
            snippet = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
            if snippet:
                top_level_lines.append(snippet)

    if top_level_lines:
        combined_globals = "\n\n".join(top_level_lines)
        total_lines = source_bytes.decode("utf-8", errors="replace").count("\n") + 1
        formatted_content = (
            f"# File: {rel_file_path} (Lines 1-{total_lines}) | Type: module_globals\n"
            f"{combined_globals}"
        )
        chunks.append(
            ExtractedChunk(
                file_path=rel_file_path,
                content=formatted_content,
                start_line=1,
                end_line=total_lines,
                node_type="module_globals",
            )
        )

    return chunks

def chunk_repository(repo_root_dir: str) -> list[ExtractedChunk]:
    """
    Walks an entire cloned repository directory, ignoring junk folders,
    and returns all extracted semantic code chunks.
    """
    all_chunks: list[ExtractedChunk] = []

    for root, dirs, files in os.walk(repo_root_dir):
        # Prune ignored directories in-place so os.walk never enters them
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file in files:
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, repo_root_dir)
            file_chunks = parse_file(abs_path, rel_path)
            all_chunks.extend(file_chunks)

    return all_chunks