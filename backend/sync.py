"""
Bidirectional synchronization between semiformal spec and generated code.

Handles:
- Spec → Code: parameter changes, renames, statement insertions
- Code → Spec: surfacing edited blocks back to spec
"""

import ast
import re
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Edit:
    """Represents an edit to code."""
    type: str  # 'add_param', 'rename_func', 'insert_statement', 'edit_line'
    location: str  # function name or line number
    content: str
    line: Optional[int] = None


@dataclass
class SyncResult:
    """Result of a synchronization operation."""
    updated_code: str
    needs_regeneration: bool
    regeneration_targets: List[str]  # Function names that need regeneration
    message: str


class BidirectionalSync:
    """Manages bidirectional synchronization between spec and code."""

    def __init__(self):
        self.spec_code = ""
        self.generated_code = ""

    def sync_spec_to_code(
        self,
        edit: Edit,
        spec_code: str,
        generated_code: str
    ) -> SyncResult:
        """
        Synchronize changes from spec to generated code.

        Args:
            edit: The edit made to the spec
            spec_code: Current semiformal spec code
            generated_code: Current generated Python code

        Returns:
            SyncResult with updated code and regeneration info
        """
        self.spec_code = spec_code
        self.generated_code = generated_code

        if edit.type == 'add_param':
            return self._handle_add_parameter(edit)
        elif edit.type == 'rename_func':
            return self._handle_rename_function(edit)
        elif edit.type == 'insert_statement':
            return self._handle_insert_statement(edit)
        else:
            return SyncResult(
                updated_code=generated_code,
                needs_regeneration=False,
                regeneration_targets=[],
                message=f"Unknown edit type: {edit.type}"
            )

    def sync_code_to_spec(
        self,
        edit: Edit,
        spec_code: str,
        generated_code: str
    ) -> SyncResult:
        """
        Synchronize changes from generated code back to spec.

        Args:
            edit: The edit made to generated code
            spec_code: Current semiformal spec code
            generated_code: Current generated Python code with edits

        Returns:
            SyncResult with updated spec code
        """
        self.spec_code = spec_code
        self.generated_code = generated_code

        if edit.type == 'edit_line':
            return self._handle_code_edit_to_spec(edit)
        else:
            return SyncResult(
                updated_code=spec_code,
                needs_regeneration=False,
                regeneration_targets=[],
                message="No spec update needed"
            )

    def _handle_add_parameter(self, edit: Edit) -> SyncResult:
        """Handle parameter addition to a function."""
        func_name = edit.location
        new_param = edit.content

        # Update function signature in generated code
        lines = self.generated_code.split('\n')
        updated_lines = []
        function_updated = False

        for line in lines:
            if f"def {func_name}(" in line:
                # Add parameter to signature
                if ')' in line:
                    # Simple case: signature on one line
                    signature = line[:line.index(')')]
                    if signature.endswith('('):
                        # No params yet
                        new_line = line.replace('():', f'({new_param}):')
                    else:
                        # Has params
                        new_line = line.replace('):', f', {new_param}):')
                    updated_lines.append(new_line)
                    function_updated = True
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)

        return SyncResult(
            updated_code='\n'.join(updated_lines),
            needs_regeneration=True,  # Need to regenerate body to use new param
            regeneration_targets=[func_name],
            message=f"Added parameter '{new_param}' to {func_name}, needs body regeneration"
        )

    def _handle_rename_function(self, edit: Edit) -> SyncResult:
        """Handle function rename (updates downstream calls)."""
        old_name = edit.location
        new_name = edit.content

        # Replace function definition and all calls
        updated_code = self.generated_code

        # Replace function definition
        updated_code = re.sub(
            rf'\bdef {old_name}\(',
            f'def {new_name}(',
            updated_code
        )

        # Replace function calls
        updated_code = re.sub(
            rf'\b{old_name}\(',
            f'{new_name}(',
            updated_code
        )

        return SyncResult(
            updated_code=updated_code,
            needs_regeneration=False,  # No regeneration needed, just rename
            regeneration_targets=[],
            message=f"Renamed {old_name} to {new_name} throughout code"
        )

    def _handle_insert_statement(self, edit: Edit) -> SyncResult:
        """Handle statement insertion into a function."""
        func_name = edit.location
        statement = edit.content

        # Determine if statement is real Python or needs LLM
        is_complete_python = self._is_complete_python_statement(statement)

        if is_complete_python:
            # Direct insertion at dependency-aware position
            updated_code = self._insert_statement_at_correct_position(
                self.generated_code,
                func_name,
                statement
            )

            return SyncResult(
                updated_code=updated_code,
                needs_regeneration=False,
                regeneration_targets=[],
                message=f"Inserted statement into {func_name}"
            )
        else:
            # Add as comment constraint and regenerate
            updated_code = self._add_constraint_comment(
                self.generated_code,
                func_name,
                statement
            )

            return SyncResult(
                updated_code=updated_code,
                needs_regeneration=True,
                regeneration_targets=[func_name],
                message=f"Added constraint to {func_name}, needs regeneration"
            )

    def _handle_code_edit_to_spec(self, edit: Edit) -> SyncResult:
        """Surface code edits back to spec."""
        edited_content = edit.content
        line_num = edit.line

        # Find which function this edit belongs to
        func_name = self._find_function_for_line(self.generated_code, line_num)

        if not func_name:
            return SyncResult(
                updated_code=self.spec_code,
                needs_regeneration=False,
                regeneration_targets=[],
                message="Edit outside function scope, no spec update"
            )

        # Find the stub in spec and append the edited line
        spec_lines = self.spec_code.split('\n')
        updated_lines = []
        in_target_func = False

        for i, line in enumerate(spec_lines):
            if f"def {func_name}(" in line:
                in_target_func = True
                updated_lines.append(line)
            elif in_target_func and "..." in line:
                # Replace ... with the edited content
                indent = len(line) - len(line.lstrip())
                updated_lines.append(' ' * indent + edited_content)
                in_target_func = False
            else:
                updated_lines.append(line)

        return SyncResult(
            updated_code='\n'.join(updated_lines),
            needs_regeneration=False,
            regeneration_targets=[],
            message=f"Surfaced edit from {func_name} to spec"
        )

    def _is_complete_python_statement(self, statement: str) -> bool:
        """Check if a statement is complete Python code."""
        try:
            ast.parse(statement)
            return '...' not in statement
        except SyntaxError:
            return False

    def _insert_statement_at_correct_position(
        self,
        code: str,
        func_name: str,
        statement: str
    ) -> str:
        """
        Insert statement at dependency-aware position in function.

        For example, if inserting print(a), find last assignment to 'a'
        and insert below it.
        """
        lines = code.split('\n')
        func_start = -1
        func_end = -1

        # Find function boundaries
        for i, line in enumerate(lines):
            if f"def {func_name}(" in line:
                func_start = i
            elif func_start >= 0 and line and not line[0].isspace() and func_end < 0:
                func_end = i
                break

        if func_end < 0:
            func_end = len(lines)

        # Extract variables used in statement
        used_vars = self._extract_variables(statement)

        # Find last assignment to any used variable
        insert_pos = func_start + 1
        for i in range(func_start + 1, func_end):
            line = lines[i]
            for var in used_vars:
                if re.match(rf'^\s*{var}\s*=', line):
                    insert_pos = i + 1

        # Get indentation from function body
        if func_start + 1 < len(lines):
            indent = len(lines[func_start + 1]) - len(lines[func_start + 1].lstrip())
        else:
            indent = 4

        # Insert statement
        lines.insert(insert_pos, ' ' * indent + statement)

        return '\n'.join(lines)

    def _add_constraint_comment(self, code: str, func_name: str, constraint: str) -> str:
        """Add a constraint comment to a function."""
        lines = code.split('\n')
        func_line = -1

        for i, line in enumerate(lines):
            if f"def {func_name}(" in line:
                func_line = i
                break

        if func_line >= 0 and func_line + 1 < len(lines):
            indent = len(lines[func_line + 1]) - len(lines[func_line + 1].lstrip())
            comment = ' ' * indent + f"# TODO: {constraint}"
            lines.insert(func_line + 1, comment)

        return '\n'.join(lines)

    def _find_function_for_line(self, code: str, line_num: int) -> Optional[str]:
        """Find which function contains the given line number."""
        lines = code.split('\n')
        if line_num > len(lines):
            return None

        current_func = None
        for i in range(line_num):
            line = lines[i]
            func_match = re.match(r'^\s*def\s+(\w+)\(', line)
            if func_match:
                current_func = func_match.group(1)

        return current_func

    def _extract_variables(self, statement: str) -> List[str]:
        """Extract variable names from a statement."""
        # Simple regex to find identifiers
        return re.findall(r'\b([a-z_][a-z0-9_]*)\b', statement, re.IGNORECASE)


def create_edit_from_spec_change(
    change_type: str,
    function_name: str,
    content: str,
    line: Optional[int] = None
) -> Edit:
    """
    Helper to create Edit objects from spec changes.

    Args:
        change_type: Type of change ('add_param', 'rename_func', etc.)
        function_name: Target function name
        content: The change content (new param name, new func name, etc.)
        line: Optional line number for line-based edits

    Returns:
        Edit object
    """
    return Edit(
        type=change_type,
        location=function_name,
        content=content,
        line=line
    )
