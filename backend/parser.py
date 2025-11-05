"""
AST-based parser for incomplete Python code.

This module identifies:
- Function calls without declarations
- Variables without assignments
- Natural language expressions (NL text)
"""

import ast
import re
from typing import List, Dict, Any, Set
from dataclasses import dataclass


@dataclass
class IncompletePart:
    """Represents an incomplete part of the code."""
    type: str  # 'function', 'variable', 'nl_text'
    name: str
    line: int
    col: int
    context: str  # surrounding code context
    value: str = ""  # for NL text or partial expressions


@dataclass
class StubDeclaration:
    """Represents a stub declaration to be created."""
    type: str  # 'function', 'variable'
    name: str
    insert_line: int
    code: str  # the stub code to insert
    original_line: int  # where the incomplete part was found


class IncompletePythonParser:
    """Parser for identifying incomplete Python code."""

    def __init__(self):
        self.defined_functions: Set[str] = set()
        self.defined_variables: Set[str] = set()
        self.incomplete_parts: List[IncompletePart] = []
        self.stubs: List[StubDeclaration] = []

    def parse(self, code: str) -> Dict[str, Any]:
        """
        Parse code and identify incomplete parts.

        Returns:
            Dict containing:
            - incomplete_parts: List of IncompletePart
            - stubs: List of StubDeclaration to create
            - annotated_code: Code with stubs inserted
        """
        self.incomplete_parts = []
        self.stubs = []
        self.defined_functions = set()
        self.defined_variables = set()

        # First pass: identify what's already defined
        self._collect_definitions(code)

        # Second pass: find incomplete parts
        self._find_incomplete_parts(code)

        # Generate stubs for incomplete parts
        self._generate_stubs()

        # Create annotated code with stubs
        annotated_code = self._insert_stubs(code)

        return {
            'incomplete_parts': [
                {
                    'type': part.type,
                    'name': part.name,
                    'line': part.line,
                    'col': part.col,
                    'context': part.context,
                    'value': part.value
                }
                for part in self.incomplete_parts
            ],
            'stubs': [
                {
                    'type': stub.type,
                    'name': stub.name,
                    'insert_line': stub.insert_line,
                    'code': stub.code,
                    'original_line': stub.original_line
                }
                for stub in self.stubs
            ],
            'annotated_code': annotated_code
        }

    def _collect_definitions(self, code: str):
        """Collect already defined functions and variables."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self.defined_functions.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.defined_variables.add(target.id)
        except SyntaxError:
            # If code doesn't parse, try line by line
            for line_num, line in enumerate(code.split('\n'), 1):
                # Try to identify function definitions
                func_match = re.match(r'^\s*def\s+(\w+)', line)
                if func_match:
                    self.defined_functions.add(func_match.group(1))

                # Try to identify variable assignments
                var_match = re.match(r'^\s*(\w+)\s*=', line)
                if var_match:
                    self.defined_variables.add(var_match.group(1))

    def _find_incomplete_parts(self, code: str):
        """Find incomplete parts in the code."""
        lines = code.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Check for function calls without definitions
            func_calls = re.findall(r'(\w+)\s*\(', line)
            for func_name in func_calls:
                if (func_name not in self.defined_functions and
                    func_name not in __builtins__ and
                    not func_name.startswith('_')):
                    self.incomplete_parts.append(IncompletePart(
                        type='function',
                        name=func_name,
                        line=line_num,
                        col=line.index(func_name),
                        context=line.strip()
                    ))

            # Check for variables without assignments (= ...)
            var_ellipsis = re.match(r'^\s*(\w+)\s*=\s*\.\.\.', line)
            if var_ellipsis:
                var_name = var_ellipsis.group(1)
                self.incomplete_parts.append(IncompletePart(
                    type='variable',
                    name=var_name,
                    line=line_num,
                    col=0,
                    context=line.strip(),
                    value='...'
                ))

            # Check for NL text (natural language in assignments)
            nl_match = re.match(r'^\s*(\w+)\s*=\s*([^=\n]+[a-zA-Z\s]{3,}.*)', line)
            if nl_match and not re.search(r'["\']', line) and '...' not in line:
                var_name = nl_match.group(1)
                nl_text = nl_match.group(2).strip()
                # Check if it looks like NL (contains spaces and letters)
                if ' ' in nl_text and not nl_text.startswith('('):
                    self.incomplete_parts.append(IncompletePart(
                        type='nl_text',
                        name=var_name,
                        line=line_num,
                        col=0,
                        context=line.strip(),
                        value=nl_text
                    ))

    def _generate_stubs(self):
        """Generate stub declarations for incomplete parts."""
        # Group incomplete parts by type
        functions_needed = {}
        variables_needed = {}

        for part in self.incomplete_parts:
            if part.type == 'function':
                if part.name not in functions_needed:
                    functions_needed[part.name] = part
            elif part.type in ('variable', 'nl_text'):
                if part.name not in variables_needed:
                    variables_needed[part.name] = part

        # Create function stubs
        for func_name, part in functions_needed.items():
            # Try to infer parameters from usage
            params = self._infer_function_params(part.context, func_name)
            stub_code = f"def {func_name}({', '.join(params)}):\n    ..."

            self.stubs.append(StubDeclaration(
                type='function',
                name=func_name,
                insert_line=part.line - 1,  # Insert before usage
                code=stub_code,
                original_line=part.line
            ))

        # Create variable stubs
        for var_name, part in variables_needed.items():
            if part.type == 'nl_text':
                # For NL text, keep it as a comment placeholder
                stub_code = f"{var_name} = ...  # {part.value}"
            else:
                stub_code = f"{var_name} = ..."

            self.stubs.append(StubDeclaration(
                type='variable',
                name=var_name,
                insert_line=part.line - 1,
                code=stub_code,
                original_line=part.line
            ))

    def _infer_function_params(self, context: str, func_name: str) -> List[str]:
        """Infer function parameters from the call context."""
        # Extract arguments from function call
        match = re.search(rf'{func_name}\s*\((.*?)\)', context)
        if match:
            args_str = match.group(1)
            if args_str.strip():
                # Count arguments
                args = [arg.strip() for arg in args_str.split(',')]
                # Generate generic parameter names
                return [f'arg{i}' for i in range(len(args))]
        return []

    def _insert_stubs(self, code: str) -> str:
        """Insert stub declarations into the code."""
        lines = code.split('\n')

        # Separate stubs into insertions and replacements
        insertions = []  # Function stubs - insert before usage
        replacements = {}  # Variable/NL stubs - replace the original line

        for stub in self.stubs:
            if stub.type == 'function':
                insertions.append(stub)
            elif stub.type == 'variable':
                # For variables, replace the original line
                replacements[stub.original_line - 1] = stub.code

        # First, handle replacements
        for line_idx, stub_code in replacements.items():
            if 0 <= line_idx < len(lines):
                lines[line_idx] = stub_code

        # Then handle insertions (in reverse to maintain line numbers)
        sorted_insertions = sorted(insertions, key=lambda s: s.insert_line, reverse=True)
        for stub in sorted_insertions:
            insert_idx = max(0, stub.insert_line)
            if insert_idx <= len(lines):
                # Don't insert if it would duplicate
                if stub.code not in '\n'.join(lines[max(0, insert_idx-2):insert_idx+2]):
                    lines.insert(insert_idx, stub.code)
                    lines.insert(insert_idx + 1, '')  # Add blank line

        return '\n'.join(lines)


def parse_incomplete_python(code: str) -> Dict[str, Any]:
    """
    Convenience function to parse incomplete Python code.

    Args:
        code: Python code that may be incomplete

    Returns:
        Dict with incomplete_parts, stubs, and annotated_code
    """
    parser = IncompletePythonParser()
    return parser.parse(code)
