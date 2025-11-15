"""
Code Deduplication Module

Removes duplicate imports, statements, and code blocks from LLM-generated code.
"""

import ast
from typing import Set, List, Tuple


class CodeDeduplicator:
    """Deduplicate generated Python code"""

    def __init__(self):
        self.seen_imports: Set[str] = set()
        self.seen_statements: Set[str] = set()

    def deduplicate(self, code: str) -> str:
        """
        Remove duplicate code while preserving order.

        Removes:
        - Duplicate imports
        - Duplicate statements (exact matches)
        - Duplicate code blocks

        Returns:
            Deduplicated code
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Can't parse, return as-is
            return code

        kept_nodes = []
        self.seen_imports = set()
        self.seen_statements = set()

        for node in tree.body:
            if self._should_keep(node, code):
                kept_nodes.append(node)

        # Reconstruct code from kept nodes
        if not kept_nodes:
            return code

        # Use ast.unparse if available (Python 3.9+), otherwise fall back
        try:
            deduplicated = '\n'.join(ast.unparse(node) for node in kept_nodes)
            return deduplicated
        except AttributeError:
            # Python < 3.9, just return original for now
            return code

    def _should_keep(self, node: ast.AST, full_code: str) -> bool:
        """
        Decide if this node should be kept or is a duplicate.
        """
        # Handle imports
        if isinstance(node, ast.Import):
            import_str = self._import_to_string(node)
            if import_str in self.seen_imports:
                return False  # Duplicate
            self.seen_imports.add(import_str)
            return True

        if isinstance(node, ast.ImportFrom):
            import_str = self._import_from_to_string(node)
            if import_str in self.seen_imports:
                return False  # Duplicate
            self.seen_imports.add(import_str)
            return True

        # Handle other statements
        try:
            stmt_str = ast.unparse(node)
        except:
            # Can't unparse, extract from source
            stmt_str = self._extract_statement_text(node, full_code)

        # Normalize whitespace for comparison
        normalized = self._normalize_statement(stmt_str)

        if normalized in self.seen_statements:
            return False  # Duplicate
        self.seen_statements.add(normalized)
        return True

    def _import_to_string(self, node: ast.Import) -> str:
        """Convert Import node to canonical string"""
        names = sorted([alias.name for alias in node.names])
        return f"import {','.join(names)}"

    def _import_from_to_string(self, node: ast.ImportFrom) -> str:
        """Convert ImportFrom node to canonical string"""
        names = sorted([alias.name for alias in node.names])
        module = node.module or ''
        return f"from {module} import {','.join(names)}"

    def _normalize_statement(self, stmt: str) -> str:
        """Normalize statement for comparison"""
        # Remove extra whitespace, comments
        lines = [line.split('#')[0].strip() for line in stmt.split('\n')]
        return ' '.join(line for line in lines if line)

    def _extract_statement_text(self, node: ast.AST, full_code: str) -> str:
        """Extract statement text from source code"""
        lines = full_code.split('\n')
        if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
            start = node.lineno - 1
            end = node.end_lineno
            return '\n'.join(lines[start:end])
        return ""


def deduplicate_code(code: str) -> str:
    """
    Convenience function to deduplicate code.

    Args:
        code: Python code potentially with duplicates

    Returns:
        Deduplicated code
    """
    deduplicator = CodeDeduplicator()
    return deduplicator.deduplicate(code)
