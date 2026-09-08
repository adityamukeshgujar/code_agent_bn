"""AST-aware code chunking.

Splits source files into chunks at function / class / component boundaries
(never fixed-size windows) using tree-sitter, for the languages this project
cares about: .py, .js, .jsx, .ts, .tsx.

Design notes:
- Nested/inner functions (closures) are intentionally NOT split out as their
  own chunks — once a function or class boundary is matched, we stop
  descending into it (except one level into a class body, to pull out its
  methods). This keeps chunks meaningful and non-overlapping.
- A React-style component (`function Foo()` / `const Foo = () => {}` /
  `const Foo = function () {}` where the name starts with an uppercase
  letter) is tagged chunk_type="component" instead of "function" — this is
  what phase 3's localizer will look for when asked about "the X page".
- `export` / `export default` wrappers are folded into the chunk's span so
  the extracted content matches what's actually in the file.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict, field
from pathlib import Path

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

PAGE_DIR_MARKERS = {"pages", "screens", "routes"}

EXT_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    # the plain "typescript" grammar rejects JSX syntax; "tsx" is the
    # superset grammar that handles JSX-bearing TypeScript.
    ".tsx": "tsx",
}

SUPPORTED_EXTENSIONS = frozenset(EXT_TO_LANGUAGE)

_JS_EXPORT_WRAPPERS = {"export_statement"}

_JS_FUNCTION_VALUE_TYPES = {"arrow_function", "function_expression"}


@dataclass
class Chunk:
    file_path: str  # POSIX-style path, relative to the repo root
    language: str
    chunk_type: str  # "function" | "class" | "method" | "component"
    symbol_name: str
    start_line: int  # 1-indexed, inclusive
    end_line: int  # 1-indexed, inclusive
    content: str
    content_hash: str
    is_page: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _is_page_path(rel_path: Path) -> bool:
    dir_parts = {p.lower() for p in rel_path.parts[:-1]}
    return bool(dir_parts & PAGE_DIR_MARKERS)


def _make_chunk(
    *,
    source: bytes,
    rel_path: str,
    language: str,
    chunk_type: str,
    symbol_name: str,
    start_node: Node,
    end_node: Node | None = None,
    is_page: bool,
) -> Chunk:
    end_node = end_node or start_node
    content = source[start_node.start_byte : end_node.end_byte].decode("utf-8", errors="replace")
    return Chunk(
        file_path=rel_path,
        language=language,
        chunk_type=chunk_type,
        symbol_name=symbol_name,
        start_line=start_node.start_point[0] + 1,
        end_line=end_node.end_point[0] + 1,
        content=content,
        content_hash=hashlib.sha1(content.encode("utf-8")).hexdigest(),
        is_page=is_page,
    )


def _text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _widen_to_export(node: Node) -> Node:
    """If `node` is directly wrapped in `export` / `export default`, use the
    wrapper's span instead so the chunk's content includes the keyword."""
    parent = node.parent
    if parent is not None and parent.type in _JS_EXPORT_WRAPPERS:
        return parent
    return node


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

def _py_unwrap_decorated(node: Node) -> Node:
    """decorated_definition -> the function_definition/class_definition it decorates,
    but the caller should still use `node` (the decorated_definition) for span."""
    if node.type != "decorated_definition":
        return node
    for child in node.named_children:
        if child.type in ("function_definition", "class_definition"):
            return child
    return node


def _py_name(def_node: Node) -> str:
    name_node = def_node.child_by_field_name("name")
    return _text(name_node) if name_node else "<anonymous>"


def _chunk_python(source: bytes, rel_path: str, is_page: bool) -> list[Chunk]:
    parser = get_parser("python")
    tree = parser.parse(source)
    chunks: list[Chunk] = []

    def visit_module_level(node: Node) -> None:
        for child in node.named_children:
            outer = child
            inner = _py_unwrap_decorated(child)
            if inner.type == "function_definition":
                chunks.append(
                    _make_chunk(
                        source=source,
                        rel_path=rel_path,
                        language="python",
                        chunk_type="function",
                        symbol_name=_py_name(inner),
                        start_node=outer,
                        is_page=is_page,
                    )
                )
            elif inner.type == "class_definition":
                class_name = _py_name(inner)
                chunks.append(
                    _make_chunk(
                        source=source,
                        rel_path=rel_path,
                        language="python",
                        chunk_type="class",
                        symbol_name=class_name,
                        start_node=outer,
                        is_page=is_page,
                    )
                )
                body = inner.child_by_field_name("body")
                if body is not None:
                    for member in body.named_children:
                        member_outer = member
                        member_inner = _py_unwrap_decorated(member)
                        if member_inner.type == "function_definition":
                            chunks.append(
                                _make_chunk(
                                    source=source,
                                    rel_path=rel_path,
                                    language="python",
                                    chunk_type="method",
                                    symbol_name=f"{class_name}.{_py_name(member_inner)}",
                                    start_node=member_outer,
                                    is_page=is_page,
                                )
                            )
            else:
                # Not a function/class boundary at this level (e.g. an `if`
                # block, decorator-free module code) — recurse one level so
                # top-level defs wrapped in simple conditionals are still found.
                if child.named_children:
                    visit_module_level(child)

    visit_module_level(tree.root_node)
    return chunks


# ---------------------------------------------------------------------------
# JavaScript / TypeScript / TSX
# ---------------------------------------------------------------------------

def _js_declarator_name(declarator: Node) -> str | None:
    name_node = declarator.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":
        return None
    return _text(name_node)


def _js_method_name(method_node: Node) -> str:
    name_node = method_node.child_by_field_name("name")
    return _text(name_node) if name_node else "<anonymous>"


def _chunk_js_like(source: bytes, rel_path: str, language: str, is_page: bool) -> list[Chunk]:
    parser = get_parser(language)
    tree = parser.parse(source)
    chunks: list[Chunk] = []

    def emit_class(class_node: Node) -> None:
        name_node = class_node.child_by_field_name("name")
        class_name = _text(name_node) if name_node else "<anonymous>"
        chunks.append(
            _make_chunk(
                source=source,
                rel_path=rel_path,
                language=language,
                chunk_type="class",
                symbol_name=class_name,
                start_node=_widen_to_export(class_node),
                is_page=is_page,
            )
        )
        body = class_node.child_by_field_name("body")
        if body is None:
            return
        for member in body.named_children:
            if member.type == "method_definition":
                chunks.append(
                    _make_chunk(
                        source=source,
                        rel_path=rel_path,
                        language=language,
                        chunk_type="method",
                        symbol_name=f"{class_name}.{_js_method_name(member)}",
                        start_node=member,
                        is_page=is_page,
                    )
                )

    def emit_function_like(name: str, span_node: Node) -> None:
        chunk_type = "component" if name and name[0:1].isupper() else "function"
        chunks.append(
            _make_chunk(
                source=source,
                rel_path=rel_path,
                language=language,
                chunk_type=chunk_type,
                symbol_name=name or "<anonymous>",
                start_node=_widen_to_export(span_node),
                is_page=is_page,
            )
        )

    def visit(node: Node) -> None:
        t = node.type
        if t == "function_declaration":
            name_node = node.child_by_field_name("name")
            emit_function_like(_text(name_node) if name_node else "<anonymous>", node)
            return  # don't descend into the function body
        if t == "class_declaration":
            emit_class(node)
            return  # methods already pulled out one level deep
        if t == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in _JS_FUNCTION_VALUE_TYPES:
                name = _js_declarator_name(node)
                # Span the whole declarator ("const Foo = () => {...}"),
                # widened to `export`/`export default` if present on the
                # enclosing variable_declaration/lexical_declaration.
                decl_parent = node.parent  # variable_declaration / lexical_declaration
                span_node = decl_parent if decl_parent is not None else node
                emit_function_like(name or "<anonymous>", span_node)
                return
        if t == "assignment_expression":
            right = node.child_by_field_name("right")
            if right is not None and right.type in _JS_FUNCTION_VALUE_TYPES:
                left = node.child_by_field_name("left")
                name = None
                if left is not None:
                    if left.type == "identifier":
                        name = _text(left)
                    elif left.type == "member_expression":
                        prop = left.child_by_field_name("property")
                        name = _text(prop) if prop is not None else None
                emit_function_like(name or "<anonymous>", node)
                return
        # Not a chunk boundary itself — recurse into children looking for one.
        for child in node.named_children:
            visit(child)

    visit(tree.root_node)
    return chunks


def chunk_source(content: str, language: str, rel_path: str, is_page: bool = False) -> list[Chunk]:
    """Chunk already-loaded source text. `rel_path` is used only for is_page
    inference when the caller hasn't already computed it and for tagging the
    resulting chunks — pass whatever you want to see in file_path."""
    source = content.encode("utf-8")
    if language == "python":
        return _chunk_python(source, rel_path, is_page)
    if language in ("javascript", "typescript", "tsx"):
        return _chunk_js_like(source, rel_path, language, is_page)
    raise ValueError(f"Unsupported language: {language!r}")


def chunk_file(path: Path, root: Path) -> list[Chunk]:
    """Chunk a file on disk. `path` is the file's absolute/actual path,
    `root` is the repo root used to compute the stored (relative) file_path."""
    ext = path.suffix.lower()
    language = EXT_TO_LANGUAGE.get(ext)
    if language is None:
        raise ValueError(f"Unsupported file extension: {ext}")
    rel_path = path.resolve().relative_to(root.resolve())
    content = path.read_text(encoding="utf-8", errors="replace")
    return chunk_source(content, language, rel_path.as_posix(), is_page=_is_page_path(rel_path))
