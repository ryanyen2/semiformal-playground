"""
MVP Edit Translator

Translates edits between semiformal and Python using:
- Phase 1: Direct AST edits
- Phase 2: Placeholder support
- Phase 3: Hole filling with LLM
- Phase 4: Completeness-based routing (direct vs LLM)
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from edit_operations import DirectEditOperations, EditResult
from generator import CodeGenerator, Mapping
from config import MVPConfig, DEFAULT_CONFIG


@dataclass
class Edit:
    """Represents an edit to code"""
    type: str  # See EDIT_MAPPING_TABLE.md for all types
    location: str  # Function name, line number, or node ID
    content: str  # The new content
    old_content: Optional[str] = None  # Previous content for comparison
    line: Optional[int] = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class EditTranslator:
    """Translate edits between semiformal and Python"""

    def __init__(
        self,
        mappings: List[Mapping],
        generator: CodeGenerator,
        config: Optional[MVPConfig] = None,
        nodes: Optional[List] = None
    ):
        """
        Initialize translator.

        Args:
            mappings: Node→code mappings from generator
            generator: CodeGenerator instance for LLM operations
            config: Configuration object (uses DEFAULT_CONFIG if None)
            nodes: IntentNode list for completeness classification
        """
        self.mappings = {m.node_id: m for m in mappings}
        self.generator = generator
        self.direct_ops = DirectEditOperations()
        self.config = config or DEFAULT_CONFIG
        self.nodes = nodes or []

        # Initialize completeness classifier if nodes provided
        self.classifier = None
        if self.nodes:
            try:
                from completeness_classifier import CompletenessClassifier
                self.classifier = CompletenessClassifier(self.nodes)
            except ImportError:
                print("Warning: CompletenessClassifier not available, falling back to type-based routing")
                self.classifier = None

    def _get_affected_nodes(self, edit: Edit) -> List:
        """
        Get IntentNodes affected by this edit.

        Uses edit.location, edit.line, and mappings to find affected nodes.
        """
        affected = []

        # Try to find by node_id (edit.location might be a node_id)
        if edit.location in self.mappings:
            mapping = self.mappings[edit.location]
            # Find the original IntentNode
            for node in self.nodes:
                if node.id == edit.location:
                    affected.append(node)
                    break

        # Try to find by line number
        if edit.line is not None:
            for node in self.nodes:
                if hasattr(node, 'span') and node.span:
                    if node.span[0] <= edit.line <= node.span[1]:
                        if node not in affected:
                            affected.append(node)

        # If still no nodes found, try to find by content matching
        if not affected and edit.old_content:
            for node in self.nodes:
                if hasattr(node, 'content') and node.content == edit.old_content:
                    if node not in affected:
                        affected.append(node)

        return affected

    def semiformal_to_python(
        self,
        edit: Edit,
        semiformal_code: str,
        python_code: str
    ) -> EditResult:
        """
        Translate semiformal edit to Python edit.

        Uses completeness-based routing (Phase 4) if classifier available:
        1. Analyze affected nodes for completeness
        2. Route based on completeness: COMPLETE → direct, INCOMPLETE → hybrid, NL → LLM

        Falls back to type-based decision tree from EDIT_MAPPING_TABLE.md:
        1. Check if direct translatable (36.6%)
        2. Check if hole fill (14.1%)
        3. Check if needs LLM (21.1%)
        4. Otherwise use placeholder/regenerate

        Args:
            edit: The edit made to semiformal code
            semiformal_code: Current semiformal code
            python_code: Current Python code

        Returns:
            EditResult with updated Python code
        """
        # Phase 4: Use completeness-based routing if classifier available
        if self.classifier:
            affected_nodes = self._get_affected_nodes(edit)

            if affected_nodes:
                # Get strategy based on node completeness
                strategy = self.classifier.get_edit_strategy(affected_nodes)

                if strategy == 'direct':
                    # All complete Python - use direct AST manipulation
                    return self._direct_translate(edit, python_code)
                elif strategy == 'hybrid':
                    # Incomplete Python - might need partial LLM
                    # For now, try direct first, fall back to LLM if needed
                    result = self._direct_translate(edit, python_code)
                    if not result.success:
                        return self._llm_translate(edit, semiformal_code, python_code)
                    return result
                elif strategy == 'llm':
                    # NL or complex semantic change - use LLM
                    return self._llm_translate(edit, semiformal_code, python_code)

        # Fallback: Route based on edit type (legacy behavior)
        if self._is_direct_translatable(edit):
            return self._direct_translate(edit, python_code)
        elif self._is_hole_fill(edit):
            return self._fill_hole_edit(edit, semiformal_code, python_code)
        elif self._needs_placeholder(edit):
            return self._add_placeholder(edit, python_code)
        elif self._needs_llm(edit):
            return self._llm_translate(edit, semiformal_code, python_code)
        else:
            # Default: mark for regeneration
            return EditResult(
                success=True,
                new_code=python_code,
                message=f"Edit type '{edit.type}' requires regeneration",
                needs_regeneration=True,
                regeneration_targets=[edit.location]
            )

    def _is_direct_translatable(self, edit: Edit) -> bool:
        """
        Check if edit can be directly mapped to Python.

        Phase 1: Direct edits (36.6% from EDIT_MAPPING_TABLE.md)
        Uses configuration instead of hardcoded list.
        """
        return edit.type in self.config.edit_types.direct_edit_types

    def _direct_translate(self, edit: Edit, python_code: str) -> EditResult:
        """
        Translate using direct AST manipulation.

        Phase 1: Direct operations
        """
        if edit.type == 'identifier_rename':
            return self.direct_ops.rename_identifier(
                python_code,
                edit.old_content or edit.location,
                edit.content
            )

        elif edit.type == 'function_rename':
            return self.direct_ops.rename_identifier(
                python_code,
                edit.old_content or edit.location,
                edit.content
            )

        elif edit.type == 'parameter_rename':
            func_name = edit.metadata.get('function_name', '')
            return self.direct_ops.rename_identifier(
                python_code,
                edit.old_content or edit.location,
                edit.content
            )

        elif edit.type == 'operator_change':
            return self.direct_ops.change_operator(
                python_code,
                edit.line or 0,
                edit.old_content or '',
                edit.content
            )

        elif edit.type == 'literal_change':
            return self.direct_ops.change_literal(
                python_code,
                edit.line or 0,
                edit.old_content,
                edit.content
            )

        elif edit.type == 'parameter_add':
            return self.direct_ops.add_parameter(
                python_code,
                edit.location,
                edit.content
            )

        elif edit.type == 'parameter_remove':
            return self.direct_ops.remove_parameter(
                python_code,
                edit.location,
                edit.content
            )

        elif edit.type == 'parameter_reorder':
            new_order = edit.metadata.get('new_order', [])
            return self.direct_ops.reorder_parameters(
                python_code,
                edit.location,
                new_order
            )

        elif edit.type == 'statement_insert':
            indent = edit.metadata.get('indent', 0)
            return self.direct_ops.insert_statement(
                python_code,
                edit.line or 0,
                edit.content,
                indent
            )

        elif edit.type == 'statement_delete':
            return self.direct_ops.delete_statement(
                python_code,
                edit.line or 0
            )

        else:
            return EditResult(
                success=False,
                new_code=python_code,
                message=f"Unknown direct edit type: {edit.type}"
            )

    def _is_hole_fill(self, edit: Edit) -> bool:
        """
        Check if this is filling a hole.

        Uses configuration instead of hardcoded list.
        """
        return edit.type in self.config.edit_types.hole_edit_types

    def _fill_hole_edit(
        self,
        edit: Edit,
        semiformal_code: str,
        python_code: str
    ) -> EditResult:
        """
        Fill a hole using LLM.

        Phase 3: Hole syntax
        """
        hint = edit.content
        target_var = edit.metadata.get('target_var')

        # Generate code to fill the hole
        filled_code = self.generator.fill_hole(hint, semiformal_code, target_var)

        # Insert at the appropriate location
        line_num = edit.line or 0
        lines = python_code.split('\n')

        if line_num < len(lines):
            # Replace the line
            indent = len(lines[line_num]) - len(lines[line_num].lstrip())
            if target_var:
                new_line = ' ' * indent + f"{target_var} = {filled_code}"
            else:
                new_line = ' ' * indent + filled_code

            lines[line_num] = new_line
            new_code = '\n'.join(lines)

            return EditResult(
                success=True,
                new_code=new_code,
                message=f"Filled hole with: {filled_code[:50]}..."
            )
        else:
            return EditResult(
                success=False,
                new_code=python_code,
                message=f"Line {line_num} out of range"
            )

    def _needs_placeholder(self, edit: Edit) -> bool:
        """
        Check if edit needs placeholder.

        Phase 2: Placeholder support (18.3%)
        Uses configuration instead of hardcoded list.
        """
        return edit.type in self.config.edit_types.placeholder_edit_types

    def _add_placeholder(self, edit: Edit, python_code: str) -> EditResult:
        """
        Add placeholder for unknown values.

        Phase 2: Placeholder support
        """
        if edit.type == 'identifier_add_lhs':
            # Use direct operation which includes placeholder logic
            return self.direct_ops.add_identifier_to_lhs(
                python_code,
                edit.line or 0,
                edit.content
            )

        elif edit.type in ('argument_add', 'variable_incomplete'):
            # Create a simple placeholder comment
            line_num = edit.line or 0
            lines = python_code.split('\n')

            if line_num < len(lines):
                indent = len(lines[line_num]) - len(lines[line_num].lstrip())
                placeholder_line = ' ' * indent + f"# TODO: {edit.content} = <placeholder>"
                lines.insert(line_num, placeholder_line)

                return EditResult(
                    success=True,
                    new_code='\n'.join(lines),
                    message=f"Added placeholder for: {edit.content}",
                    needs_regeneration=True
                )

        return EditResult(
            success=False,
            new_code=python_code,
            message=f"Unsupported placeholder type: {edit.type}"
        )

    def _needs_llm(self, edit: Edit) -> bool:
        """
        Check if edit needs LLM.

        Phase 3: LLM integration (21.1%)
        Uses configuration instead of hardcoded list.
        """
        return edit.type in self.config.edit_types.llm_edit_types

    def _llm_translate(
        self,
        edit: Edit,
        semiformal_code: str,
        python_code: str
    ) -> EditResult:
        """
        Translate using LLM for complex semantic changes.

        Phase 3: LLM integration
        """
        # For now, mark for regeneration
        # Full LLM translation would involve regenerating affected code sections
        return EditResult(
            success=True,
            new_code=python_code,
            message=f"LLM translation for '{edit.type}' requires regeneration",
            needs_regeneration=True,
            regeneration_targets=[edit.location]
        )


class UpdateDecider:
    """Decide if and how Python→Semiformal edits should propagate"""

    def __init__(self, config: Optional[MVPConfig] = None):
        """
        Initialize update decider.

        Args:
            config: Configuration object (uses DEFAULT_CONFIG if None)
        """
        self.config = config or DEFAULT_CONFIG

    def should_propagate(self, edit: Edit) -> Tuple[bool, str]:
        """
        Decide if Python edit should propagate to semiformal.

        Uses configuration patterns instead of hardcoded lists.

        Returns:
            (should_propagate, strategy)
        """
        # Check if it's a transient edit (don't propagate)
        if any(pattern in edit.type for pattern in self.config.edit_types.transient_patterns):
            return False, 'none'

        # Check if it's a semantic change (must propagate)
        if any(pattern in edit.type for pattern in self.config.edit_types.semantic_patterns):
            return True, 'llm'

        # Default: optional (ask user or use heuristic)
        return self._is_significant_change(edit), 'llm'

    def _is_significant_change(self, edit: Edit) -> bool:
        """Heuristic to determine if change is significant"""
        # Simple heuristic: changes > 3 lines are significant
        if edit.metadata.get('lines_changed', 1) > 3:
            return True

        # Changes to function signatures are significant
        if 'function' in edit.type.lower():
            return True

        return False
