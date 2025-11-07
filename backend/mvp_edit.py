"""
MVP Direct Edit Operations (Phase 1)

Implements direct AST-based edits that don't require LLM:
- Variable/function/parameter renames
- Operator changes
- Literal value changes
- Argument reordering
- Simple statement insertion/deletion
"""

import ast
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any


@dataclass
class EditResult:
    """Result of applying an edit"""
    success: bool
    new_code: str
    message: str
    needs_regeneration: bool = False
    regeneration_targets: List[str] = None  # Function names to regenerate

    def __post_init__(self):
        if self.regeneration_targets is None:
            self.regeneration_targets = []


class DirectEditOperations:
    """Handles direct AST-based edit operations"""

    @staticmethod
    def rename_identifier(code: str, old_name: str, new_name: str) -> EditResult:
        """
        Rename a variable, function, or parameter throughout the code.

        Strategy: Direct AST manipulation (36.6% category from EDIT_MAPPING_TABLE.md)
        """
        try:
            tree = ast.parse(code)
            renamed = False

            class IdentifierRenamer(ast.NodeTransformer):
                def visit_Name(self, node):
                    nonlocal renamed
                    if node.id == old_name:
                        node.id = new_name
                        renamed = True
                    return node

                def visit_FunctionDef(self, node):
                    if node.name == old_name:
                        node.name = new_name
                        renamed = True
                    # Also rename parameters
                    for arg in node.args.args:
                        if arg.arg == old_name:
                            arg.arg = new_name
                            renamed = True
                    self.generic_visit(node)
                    return node

                def visit_arg(self, node):
                    nonlocal renamed
                    if node.arg == old_name:
                        node.arg = new_name
                        renamed = True
                    return node

            transformer = IdentifierRenamer()
            new_tree = transformer.visit(tree)
            new_code = ast.unparse(new_tree)

            if renamed:
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Renamed '{old_name}' to '{new_name}' throughout code"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"'{old_name}' not found in code"
                )

        except SyntaxError as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Syntax error: {str(e)}"
            )

    @staticmethod
    def change_operator(code: str, line_num: int, old_op: str, new_op: str) -> EditResult:
        """
        Change an operator on a specific line.

        Examples: + -> -, > -> >=, and -> or
        Strategy: Direct AST manipulation
        """
        lines = code.split('\n')
        if line_num >= len(lines):
            return EditResult(
                success=False,
                new_code=code,
                message=f"Line {line_num} out of range"
            )

        target_line = lines[line_num]

        # Simple string replacement for operators
        # This handles most cases; for complex expressions, use AST
        if old_op in target_line:
            new_line = target_line.replace(old_op, new_op, 1)
            lines[line_num] = new_line
            new_code = '\n'.join(lines)

            return EditResult(
                success=True,
                new_code=new_code,
                message=f"Changed operator '{old_op}' to '{new_op}' on line {line_num}"
            )
        else:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Operator '{old_op}' not found on line {line_num}"
            )

    @staticmethod
    def change_literal(code: str, line_num: int, old_value: Any, new_value: Any) -> EditResult:
        """
        Change a literal value on a specific line.

        Examples: 5 -> 10, "hello" -> "world", True -> False
        Strategy: Direct AST manipulation
        """
        lines = code.split('\n')
        if line_num >= len(lines):
            return EditResult(
                success=False,
                new_code=code,
                message=f"Line {line_num} out of range"
            )

        target_line = lines[line_num]
        old_str = str(old_value)
        new_str = str(new_value)

        # Handle string literals specially
        if isinstance(old_value, str):
            old_str = f'"{old_value}"'
            new_str = f'"{new_value}"'

        if old_str in target_line:
            new_line = target_line.replace(old_str, new_str, 1)
            lines[line_num] = new_line
            new_code = '\n'.join(lines)

            return EditResult(
                success=True,
                new_code=new_code,
                message=f"Changed literal '{old_value}' to '{new_value}' on line {line_num}"
            )
        else:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Literal '{old_value}' not found on line {line_num}"
            )

    @staticmethod
    def add_identifier_to_lhs(code: str, line_num: int, new_identifier: str) -> EditResult:
        """
        Add an identifier to the left-hand side of an assignment.

        Example: x = ... -> x, y = ...
        Strategy: Direct + Placeholder (from EDIT_MAPPING_TABLE.md)
        Requires: RHS needs to be updated to return multiple values
        """
        try:
            lines = code.split('\n')
            if line_num >= len(lines):
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Line {line_num} out of range"
                )

            target_line = lines[line_num]
            tree = ast.parse(target_line)

            if not tree.body or not isinstance(tree.body[0], ast.Assign):
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Line {line_num} is not an assignment"
                )

            assign = tree.body[0]
            target = assign.targets[0]

            # Convert single target to tuple or extend existing tuple
            if isinstance(target, ast.Name):
                # Single target -> make it a tuple
                new_target = ast.Tuple(
                    elts=[target, ast.Name(id=new_identifier, ctx=ast.Store())],
                    ctx=ast.Store()
                )
            elif isinstance(target, ast.Tuple):
                # Already a tuple -> add to it
                target.elts.append(ast.Name(id=new_identifier, ctx=ast.Store()))
                new_target = target
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message="Unsupported assignment target type"
                )

            assign.targets[0] = new_target
            new_line = ast.unparse(tree)
            lines[line_num] = new_line

            return EditResult(
                success=True,
                new_code='\n'.join(lines),
                message=f"Added '{new_identifier}' to LHS on line {line_num}",
                needs_regeneration=True,
                regeneration_targets=['rhs_of_assignment']
            )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error: {str(e)}"
            )

    @staticmethod
    def add_parameter(code: str, function_name: str, param_name: str) -> EditResult:
        """
        Add a parameter to a function signature.

        Example: def f(a): -> def f(a, b):
        Strategy: Direct + Regenerate (body needs updating)
        """
        try:
            tree = ast.parse(code)
            modified = False

            class ParameterAdder(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    nonlocal modified
                    if node.name == function_name:
                        # Add new parameter
                        new_arg = ast.arg(arg=param_name, annotation=None)
                        node.args.args.append(new_arg)
                        modified = True
                    self.generic_visit(node)
                    return node

            transformer = ParameterAdder()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Added parameter '{param_name}' to function '{function_name}'",
                    needs_regeneration=True,
                    regeneration_targets=[function_name]
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Function '{function_name}' not found"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error: {str(e)}"
            )

    @staticmethod
    def remove_parameter(code: str, function_name: str, param_name: str) -> EditResult:
        """
        Remove a parameter from a function signature.

        Example: def f(a, b): -> def f(a):
        Strategy: Direct + Regenerate
        """
        try:
            tree = ast.parse(code)
            modified = False

            class ParameterRemover(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    nonlocal modified
                    if node.name == function_name:
                        # Remove parameter
                        node.args.args = [arg for arg in node.args.args if arg.arg != param_name]
                        modified = True
                    self.generic_visit(node)
                    return node

            transformer = ParameterRemover()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Removed parameter '{param_name}' from function '{function_name}'",
                    needs_regeneration=True,
                    regeneration_targets=[function_name]
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Parameter '{param_name}' not found in function '{function_name}'"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error: {str(e)}"
            )

    @staticmethod
    def insert_statement(code: str, line_num: int, statement: str, indent: int = 0) -> EditResult:
        """
        Insert a statement at a specific line.

        Strategy: Direct (if valid Python)
        """
        try:
            # Validate that statement is valid Python
            ast.parse(statement)

            lines = code.split('\n')
            indented_statement = ' ' * indent + statement
            lines.insert(line_num, indented_statement)

            return EditResult(
                success=True,
                new_code='\n'.join(lines),
                message=f"Inserted statement at line {line_num}"
            )

        except SyntaxError:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Invalid Python statement: {statement}"
            )

    @staticmethod
    def delete_statement(code: str, line_num: int) -> EditResult:
        """
        Delete a statement at a specific line.

        Strategy: Direct
        """
        lines = code.split('\n')
        if line_num >= len(lines):
            return EditResult(
                success=False,
                new_code=code,
                message=f"Line {line_num} out of range"
            )

        deleted_line = lines[line_num]
        del lines[line_num]

        return EditResult(
            success=True,
            new_code='\n'.join(lines),
            message=f"Deleted statement at line {line_num}: {deleted_line.strip()}"
        )

    @staticmethod
    def reorder_parameters(code: str, function_name: str, new_order: List[str]) -> EditResult:
        """
        Reorder parameters in a function signature.

        Example: def f(a, b, c): -> def f(b, a, c):
        Strategy: Direct
        """
        try:
            tree = ast.parse(code)
            modified = False

            class ParameterReorderer(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    nonlocal modified
                    if node.name == function_name:
                        # Create mapping of param names to arg objects
                        param_map = {arg.arg: arg for arg in node.args.args}

                        # Check all params in new_order exist
                        if set(new_order) != set(param_map.keys()):
                            return node  # Invalid reorder

                        # Reorder
                        node.args.args = [param_map[name] for name in new_order]
                        modified = True

                    self.generic_visit(node)
                    return node

            transformer = ParameterReorderer()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Reordered parameters of function '{function_name}'"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Could not reorder parameters for function '{function_name}'"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error: {str(e)}"
            )
