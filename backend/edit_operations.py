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
from typing import Optional, List


@dataclass
class EditResult:
    """Result of applying an edit"""
    success: bool
    new_code: str
    message: str
    needs_regeneration: bool = False
    regeneration_targets: List[str] = None
    # Optional richer information for higher-level orchestrators (editor/translator)
    # to update IR nodes and mappings after LLM-based regeneration.
    new_nodes: Optional[List] = None
    new_mappings: Optional[List] = None

    def __post_init__(self):
        if self.regeneration_targets is None:
            self.regeneration_targets = []


class DirectEditOperations:
    """Handles direct AST-based edit operations"""

    @staticmethod
    def rename_identifier(code: str, old_name: str, new_name: str) -> EditResult:
        """Rename a variable, function, or parameter throughout the code."""
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
        """Change an operator on a specific line."""
        lines = code.split('\n')
        if line_num >= len(lines):
            return EditResult(
                success=False,
                new_code=code,
                message=f"Line {line_num} out of range"
            )

        target_line = lines[line_num]
        if old_op in target_line:
            new_line = target_line.replace(old_op, new_op, 1)
            lines[line_num] = new_line
            return EditResult(
                success=True,
                new_code='\n'.join(lines),
                message=f"Changed operator '{old_op}' to '{new_op}' on line {line_num}"
            )
        else:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Operator '{old_op}' not found on line {line_num}"
            )

    @staticmethod
    def change_literal(code: str, line_num: int, old_value: any, new_value: any) -> EditResult:
        """Change a literal value on a specific line."""
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

        if isinstance(old_value, str):
            old_str = f'"{old_value}"'
            new_str = f'"{new_value}"'

        if old_str in target_line:
            new_line = target_line.replace(old_str, new_str, 1)
            lines[line_num] = new_line
            return EditResult(
                success=True,
                new_code='\n'.join(lines),
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
        """Add an identifier to the left-hand side of an assignment."""
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

            if isinstance(target, ast.Name):
                new_target = ast.Tuple(
                    elts=[target, ast.Name(id=new_identifier, ctx=ast.Store())],
                    ctx=ast.Store()
                )
            elif isinstance(target, ast.Tuple):
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
    def add_function_call_argument(
        code: str,
        function_name: str,
        line_num: int,
        arg_value: str,
        arg_name: Optional[str] = None
    ) -> EditResult:
        """Add an argument to a function call."""
        try:
            tree = ast.parse(code)
            modified = False

            class ArgumentAdder(ast.NodeTransformer):
                def visit_Call(self, node):
                    nonlocal modified
                    if hasattr(node, 'lineno') and node.lineno - 1 == line_num:
                        if isinstance(node.func, ast.Name) and node.func.id == function_name:
                            try:
                                value_ast = ast.parse(arg_value, mode='eval').body
                                if arg_name:
                                    node.keywords.append(
                                        ast.keyword(arg=arg_name, value=value_ast)
                                    )
                                else:
                                    node.args.append(value_ast)
                                modified = True
                            except:
                                pass
                    self.generic_visit(node)
                    return node

            transformer = ArgumentAdder()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                arg_desc = f"{arg_name}={arg_value}" if arg_name else arg_value
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Added argument '{arg_desc}' to function call '{function_name}' on line {line_num}"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Function call '{function_name}' not found on line {line_num}"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error adding argument: {str(e)}"
            )

    @staticmethod
    def remove_function_call_argument(
        code: str,
        function_name: str,
        line_num: int,
        arg_index: Optional[int] = None,
        arg_name: Optional[str] = None
    ) -> EditResult:
        """Remove an argument from a function call."""
        try:
            tree = ast.parse(code)
            modified = False

            class ArgumentRemover(ast.NodeTransformer):
                def visit_Call(self, node):
                    nonlocal modified
                    if hasattr(node, 'lineno') and node.lineno - 1 == line_num:
                        if isinstance(node.func, ast.Name) and node.func.id == function_name:
                            if arg_name:
                                original_len = len(node.keywords)
                                node.keywords = [
                                    kw for kw in node.keywords if kw.arg != arg_name
                                ]
                                modified = len(node.keywords) < original_len
                            elif arg_index is not None and 0 <= arg_index < len(node.args):
                                del node.args[arg_index]
                                modified = True
                    self.generic_visit(node)
                    return node

            transformer = ArgumentRemover()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                arg_desc = arg_name if arg_name else f"argument at index {arg_index}"
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Removed {arg_desc} from function call '{function_name}' on line {line_num}"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Argument not found in function call '{function_name}' on line {line_num}"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error removing argument: {str(e)}"
            )

    @staticmethod
    def change_function_call_name(
        code: str,
        old_name: str,
        new_name: str,
        line_num: Optional[int] = None
    ) -> EditResult:
        """Change the name of a function call."""
        try:
            tree = ast.parse(code)
            modified = False

            class FunctionCallRenamer(ast.NodeTransformer):
                def visit_Call(self, node):
                    nonlocal modified
                    if isinstance(node.func, ast.Name) and node.func.id == old_name:
                        if line_num is None or (hasattr(node, 'lineno') and node.lineno - 1 == line_num):
                            node.func.id = new_name
                            modified = True
                    self.generic_visit(node)
                    return node

            transformer = FunctionCallRenamer()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                location = f"on line {line_num}" if line_num is not None else "throughout code"
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Renamed function call '{old_name}' to '{new_name}' {location}"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Function call '{old_name}' not found"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error renaming function call: {str(e)}"
            )

    @staticmethod
    def change_function_call_argument(
        code: str,
        function_name: str,
        line_num: int,
        arg_index: Optional[int] = None,
        arg_name: Optional[str] = None,
        new_value: str = None
    ) -> EditResult:
        """Change the value of a specific argument in a function call."""
        try:
            tree = ast.parse(code)
            modified = False

            class ArgumentChanger(ast.NodeTransformer):
                def visit_Call(self, node):
                    nonlocal modified
                    if hasattr(node, 'lineno') and node.lineno - 1 == line_num:
                        if isinstance(node.func, ast.Name) and node.func.id == function_name:
                            try:
                                new_value_ast = ast.parse(new_value, mode='eval').body
                                if arg_name:
                                    for kw in node.keywords:
                                        if kw.arg == arg_name:
                                            kw.value = new_value_ast
                                            modified = True
                                            break
                                elif arg_index is not None and 0 <= arg_index < len(node.args):
                                    node.args[arg_index] = new_value_ast
                                    modified = True
                            except:
                                pass
                    self.generic_visit(node)
                    return node

            transformer = ArgumentChanger()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                arg_desc = arg_name if arg_name else f"argument at index {arg_index}"
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Changed {arg_desc} to '{new_value}' in function call '{function_name}' on line {line_num}"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Could not change argument in function call '{function_name}' on line {line_num}"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error changing argument: {str(e)}"
            )

    @staticmethod
    def reorder_function_call_arguments(
        code: str,
        function_name: str,
        line_num: int,
        new_order: List[int]
    ) -> EditResult:
        """Reorder positional arguments in a function call."""
        try:
            tree = ast.parse(code)
            modified = False

            class ArgumentReorderer(ast.NodeTransformer):
                def visit_Call(self, node):
                    nonlocal modified
                    if hasattr(node, 'lineno') and node.lineno - 1 == line_num:
                        if isinstance(node.func, ast.Name) and node.func.id == function_name:
                            if (len(new_order) == len(node.args) and
                                set(new_order) == set(range(len(node.args)))):
                                old_args = node.args.copy()
                                node.args = [old_args[i] for i in new_order]
                                modified = True
                    self.generic_visit(node)
                    return node

            transformer = ArgumentReorderer()
            new_tree = transformer.visit(tree)

            if modified:
                new_code = ast.unparse(new_tree)
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Reordered arguments in function call '{function_name}' on line {line_num}"
                )
            else:
                return EditResult(
                    success=False,
                    new_code=code,
                    message=f"Could not reorder arguments for function call '{function_name}' on line {line_num}"
                )

        except Exception as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Error reordering arguments: {str(e)}"
            )

    @staticmethod
    def add_parameter(code: str, function_name: str, param_name: str) -> EditResult:
        """Add a parameter to a function signature."""
        try:
            tree = ast.parse(code)
            modified = False

            class ParameterAdder(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    nonlocal modified
                    if node.name == function_name:
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
        """Remove a parameter from a function signature."""
        try:
            tree = ast.parse(code)
            modified = False

            class ParameterRemover(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    nonlocal modified
                    if node.name == function_name:
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
    def reorder_parameters(code: str, function_name: str, new_order: List[str]) -> EditResult:
        """Reorder parameters in a function signature."""
        try:
            tree = ast.parse(code)
            modified = False

            class ParameterReorderer(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    nonlocal modified
                    if node.name == function_name:
                        param_map = {arg.arg: arg for arg in node.args.args}
                        if set(new_order) == set(param_map.keys()):
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

    @staticmethod
    def insert_statement(code: str, line_num: int, statement: str, indent: int = 0) -> EditResult:
        """Insert a statement at a specific line."""
        try:
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
        """Delete a statement at a specific line."""
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
    def replace_statement(code: str, line_num: int, new_statement: str) -> EditResult:
        """
        Replace a statement at a specific line with new content.
        
        This preserves all other lines, fixing the "code disappearing" issue.
        Only the target line is modified.
        
        Args:
            code: Current Python code
            line_num: Line number to replace (0-indexed)
            new_statement: New statement content
            
        Returns:
            EditResult with updated code
        """
        lines = code.split('\n')
        if line_num >= len(lines):
            return EditResult(
                success=False,
                new_code=code,
                message=f"Line {line_num} out of range (code has {len(lines)} lines)"
            )
        
        old_line = lines[line_num]
        
        # Preserve indentation from old line if new statement doesn't have it
        old_indent = len(old_line) - len(old_line.lstrip())
        new_indent = len(new_statement) - len(new_statement.lstrip())
        
        if new_indent == 0 and old_indent > 0:
            # New statement has no indentation, but old one did - preserve it
            new_statement = ' ' * old_indent + new_statement.lstrip()
        
        # Replace the line
        lines[line_num] = new_statement
        
        return EditResult(
            success=True,
            new_code='\n'.join(lines),
            message=f"Replaced line {line_num}: '{old_line.strip()}' → '{new_statement.strip()}'"
        )