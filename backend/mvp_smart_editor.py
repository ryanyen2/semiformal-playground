"""
Smart Edit Coordinator

Handles intelligent editing with bidirectional sync between function calls and definitions.
Routes edits to either direct AST manipulation or LLM regeneration based on the change type.
"""

import ast
import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

from mvp_edit import DirectEditOperations, EditResult


@dataclass
class FunctionCallEdit:
    """Represents an edit to a function call"""
    function_name: str
    line_num: int
    edit_type: str  # 'add_arg', 'remove_arg', 'change_arg', 'rename'
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    arg_name: Optional[str] = None
    arg_index: Optional[int] = None


class SmartEditCoordinator:
    """Coordinates edits between function calls and definitions"""

    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize smart edit coordinator.

        Args:
            openai_api_key: OpenAI API key for LLM-based regeneration
        """
        self.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')

        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except:
                self.client = None
        else:
            self.client = None

    def apply_function_call_edit(
        self,
        code: str,
        edit: FunctionCallEdit,
        sync_definition: bool = True
    ) -> EditResult:
        """
        Apply an edit to a function call and optionally sync with its definition.

        Args:
            code: Python code to edit
            edit: Edit to apply
            sync_definition: Whether to sync changes to the function definition

        Returns:
            EditResult with updated code
        """
        # Step 1: Apply the edit to the function call
        if edit.edit_type == 'add_arg':
            result = DirectEditOperations.add_function_call_argument(
                code=code,
                function_name=edit.function_name,
                line_num=edit.line_num,
                arg_value=edit.new_value,
                arg_name=edit.arg_name
            )
        elif edit.edit_type == 'remove_arg':
            result = DirectEditOperations.remove_function_call_argument(
                code=code,
                function_name=edit.function_name,
                line_num=edit.line_num,
                arg_index=edit.arg_index,
                arg_name=edit.arg_name
            )
        elif edit.edit_type == 'change_arg':
            # Determine if this is a literal change or semantic change
            if self._is_literal_change(edit):
                # Direct edit - no LLM needed
                result = DirectEditOperations.change_function_call_argument(
                    code=code,
                    function_name=edit.function_name,
                    line_num=edit.line_num,
                    arg_index=edit.arg_index,
                    arg_name=edit.arg_name,
                    new_value=edit.new_value
                )
                # For literal changes, we might still need to update the function body
                # if the literal affects behavior
                if sync_definition and self._affects_function_logic(edit):
                    result = self._sync_definition_after_edit(
                        result.new_code, edit.function_name, edit
                    )
            else:
                # Semantic change - might need LLM
                result = DirectEditOperations.change_function_call_argument(
                    code=code,
                    function_name=edit.function_name,
                    line_num=edit.line_num,
                    arg_index=edit.arg_index,
                    arg_name=edit.arg_name,
                    new_value=edit.new_value
                )
        elif edit.edit_type == 'rename':
            result = DirectEditOperations.change_function_call_name(
                code=code,
                old_name=edit.old_value,
                new_name=edit.new_value,
                line_num=edit.line_num
            )
            # Rename should also rename the definition
            if sync_definition:
                result = self._sync_definition_rename(
                    result.new_code, edit.old_value, edit.new_value
                )
        else:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Unknown edit type: {edit.edit_type}"
            )

        # Step 2: Sync with function definition if needed
        if not result.success:
            return result

        if sync_definition and edit.edit_type in ('add_arg', 'remove_arg'):
            # These require updating the function signature and possibly the body
            result = self._sync_definition_after_edit(
                result.new_code, edit.function_name, edit
            )

        return result

    def _is_literal_change(self, edit: FunctionCallEdit) -> bool:
        """Check if an edit is a simple literal value change"""
        if edit.edit_type != 'change_arg':
            return False

        # Check if new_value is a literal (number, string, boolean)
        try:
            ast.parse(edit.new_value, mode='eval')
            # If it parses as a simple literal, it's a literal change
            tree = ast.parse(edit.new_value, mode='eval')
            return isinstance(tree.body, ast.Constant)
        except:
            return False

    def _affects_function_logic(self, edit: FunctionCallEdit) -> bool:
        """Check if a literal change significantly affects function logic"""
        # For now, assume literal changes don't require function body updates
        # This is a heuristic that can be refined
        return False

    def _sync_definition_after_edit(
        self,
        code: str,
        function_name: str,
        edit: FunctionCallEdit
    ) -> EditResult:
        """
        Sync function definition after editing a call.

        This updates both the signature and regenerates the body if needed.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return EditResult(
                success=False,
                new_code=code,
                message=f"Cannot sync: code has syntax errors: {e}"
            )

        # Find the function definition
        func_def = None
        func_def_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                func_def_node = node
                func_def = ast.unparse(node)
                break

        if not func_def_node:
            # No definition found - nothing to sync
            return EditResult(
                success=True,
                new_code=code,
                message=f"No definition found for {function_name}, call updated only"
            )

        # Update the function signature based on the edit
        if edit.edit_type == 'add_arg':
            # Add parameter to function signature
            if edit.arg_name:
                # Keyword argument - add with default value
                new_arg = ast.arg(arg=edit.arg_name, annotation=None)
                try:
                    default_val = ast.parse(edit.new_value, mode='eval').body
                    func_def_node.args.defaults.append(default_val)
                    func_def_node.args.args.append(new_arg)
                except:
                    pass
            else:
                # Positional argument - harder to handle, skip for now
                pass

        elif edit.edit_type == 'remove_arg':
            # Remove parameter from function signature
            if edit.arg_name:
                # Remove keyword argument
                for i, arg in enumerate(func_def_node.args.args):
                    if arg.arg == edit.arg_name:
                        del func_def_node.args.args[i]
                        # Also remove default if present
                        if i < len(func_def_node.args.defaults):
                            del func_def_node.args.defaults[i]
                        break

        # Regenerate the function body if LLM is available
        if self.client and edit.edit_type in ('add_arg', 'remove_arg'):
            new_func_def = self._regenerate_function_body(func_def_node, code, edit)
            if new_func_def:
                # Replace the old function definition with the new one
                new_code = code.replace(func_def, new_func_def)
                return EditResult(
                    success=True,
                    new_code=new_code,
                    message=f"Updated {function_name} call and regenerated definition",
                    needs_regeneration=False
                )

        # No LLM - just update the signature
        new_func_def = ast.unparse(func_def_node)
        new_code = code.replace(func_def, new_func_def)
        return EditResult(
            success=True,
            new_code=new_code,
            message=f"Updated {function_name} signature (body needs manual update)",
            needs_regeneration=True,
            regeneration_targets=[function_name]
        )

    def _regenerate_function_body(
        self,
        func_node: ast.FunctionDef,
        context: str,
        edit: FunctionCallEdit
    ) -> Optional[str]:
        """Regenerate function body using LLM"""
        if not self.client:
            return None

        # Build prompt for function body regeneration
        func_sig = f"def {func_node.name}({ast.unparse(func_node.args)}):"

        # Get docstring if present
        docstring = ast.get_docstring(func_node) or ""

        prompt = f"""Regenerate the function body for this function after parameter changes.

**Function signature:**
```python
{func_sig}
```

**Original docstring:**
{docstring if docstring else "(none)"}

**Edit made:** {edit.edit_type}
{f"Added parameter: {edit.arg_name}={edit.new_value}" if edit.edit_type == 'add_arg' else ''}
{f"Removed parameter: {edit.arg_name}" if edit.edit_type == 'remove_arg' else ''}

**Context:**
```python
{context}
```

**Requirements:**
1. Generate a complete function implementation
2. Use all parameters appropriately
3. Maintain the function's original intent
4. Include proper docstring
5. Add error handling if needed

Generate the complete function definition:
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert Python developer. Generate clean, working function implementations."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )

            generated = response.choices[0].message.content.strip()

            # Extract code from markdown
            import re
            match = re.search(r'```python\n(.*?)\n```', generated, re.DOTALL)
            if match:
                return match.group(1)
            else:
                return generated

        except Exception as e:
            print(f"Error regenerating function body: {e}")
            return None

    def _sync_definition_rename(
        self,
        code: str,
        old_name: str,
        new_name: str
    ) -> EditResult:
        """Sync function definition after renaming"""
        # Use the rename_identifier operation which handles both calls and definitions
        return DirectEditOperations.rename_identifier(code, old_name, new_name)

