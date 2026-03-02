from __future__ import annotations

import ast


def slim_source(source: str) -> str:
    """Return a slimmed view of a Python source file.

    Strips imports and private/dunder members. Replaces function/method bodies
    with '...', preserving the original signature lines and any leading docstring.
    Uses AST to decide what to keep but emits original source lines to preserve
    formatting (including multiline docstrings).
    """
    lines = source.splitlines()
    tree = ast.parse(source)

    def emit_lines(start: int | None, end: int | None, out: list[str]) -> None:
        if start is None or end is None:
            return
        out.extend(lines[start - 1 : end])

    def is_docstring(node: ast.stmt) -> bool:
        return (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )

    def process_stmts(stmts: list[ast.stmt], out: list[str]) -> None:
        for node in stmts:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            elif isinstance(node, ast.ClassDef):
                process_class(node, out)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "__init__" or not node.name.startswith("_"):
                    process_func(node, out)
            elif isinstance(node, (ast.AnnAssign, ast.Assign)):
                if (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id.startswith("_")
                ):
                    continue
                emit_lines(node.lineno, node.end_lineno, out)
            elif is_docstring(node):
                emit_lines(node.lineno, node.end_lineno, out)

    def process_class(node: ast.ClassDef, out: list[str]) -> None:
        for dec in node.decorator_list:
            emit_lines(dec.lineno, dec.end_lineno, out)
        emit_lines(node.lineno, node.body[0].lineno - 1, out)
        process_stmts(node.body, out)

    def process_func(
        node: ast.FunctionDef | ast.AsyncFunctionDef, out: list[str]
    ) -> None:
        for dec in node.decorator_list:
            emit_lines(dec.lineno, dec.end_lineno, out)
        emit_lines(node.lineno, node.body[0].lineno - 1, out)
        if is_docstring(node.body[0]):
            emit_lines(node.body[0].lineno, node.body[0].end_lineno, out)
        def_line = lines[node.lineno - 1]
        stub_indent = " " * (len(def_line) - len(def_line.lstrip()) + 4)
        out.append(f"{stub_indent}...")

    out: list[str] = []
    first = True
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not first:
            out.append("")
        first = False
        tmp: list[str] = []
        if isinstance(node, ast.ClassDef):
            process_class(node, tmp)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                first = True
                continue
            process_func(node, tmp)
        elif isinstance(node, (ast.AnnAssign, ast.Assign)):
            emit_lines(node.lineno, node.end_lineno, tmp)
        elif is_docstring(node):
            emit_lines(node.lineno, node.end_lineno, tmp)
        else:
            first = True
            continue
        out.extend(tmp)

    return "\n".join(out)
