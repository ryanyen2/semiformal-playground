"""
MVP Edit Translator

Translates edits between semiformal and Python using:
- Direct AST edits for complete Python
- LLM regeneration for NL/hole content changes
- Node type-based routing (simpler than completeness classification)
"""

import ast
from dataclasses import dataclass
from typing import List, Optional, Tuple
from edit_operations import DirectEditOperations, EditResult
from generator import CodeGenerator, Mapping
from config import MVPConfig, DEFAULT_CONFIG


@dataclass
class Edit:
    """Represents an edit to code"""
    location: str  # Function name, line number, or node ID
    content: str  # The new content
    old_content: Optional[str] = None  # Previous content for comparison
    line: Optional[int] = None
    metadata: dict = None
    type: Optional[str] = None  # Edit type (inferred by backend if not provided)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class EditTypeInferrer:
    """Infers edit type from semiformal code changes"""
    
    @staticmethod
    def infer_edit_type(edit: Edit, semiformal_line: str, old_semiformal_line: Optional[str] = None) -> str:
        """
        Infer edit type based on what changed in the semiformal code.
        
        Strategy:
        1. Check if the line is valid Python → Python statement edit
        2. Check if contains holes {} or NL → mixed/incomplete edit
        3. Check specific patterns (rename, operator change, etc.)
        
        Returns:
            Edit type string (e.g., 'python_statement_edit', 'identifier_rename', 'nl_edit')
        """
        # Try to parse as Python
        try:
            tree = ast.parse(semiformal_line.strip())
            # It's valid Python - determine what kind of Python edit
            
            # If we have old content, check what changed
            if old_semiformal_line:
                return EditTypeInferrer._infer_python_edit_type(
                    semiformal_line, 
                    old_semiformal_line,
                    tree
                )
            
            # New line - check statement type
            if tree.body:
                stmt = tree.body[0]
                if isinstance(stmt, ast.Assign):
                    return 'python_assignment_edit'
                elif isinstance(stmt, ast.Expr):
                    return 'python_expression_edit'
                elif isinstance(stmt, ast.FunctionDef):
                    return 'python_function_def_edit'
            
            return 'python_statement_edit'
            
        except SyntaxError:
            # Not valid Python - check for semiformal constructs
            line = semiformal_line.strip()
            
            # Check for holes
            if '{' in line and '}' in line:
                return 'hole_edit'
            
            # Check for assignment with NL
            if '=' in line:
                return 'nl_assignment_edit'
            
            return 'nl_edit'
    
    @staticmethod
    def _infer_python_edit_type(new_line: str, old_line: str, tree: ast.AST) -> str:
        """Infer specific Python edit type by comparing old and new"""
        
        # Check for identifier rename (simple case)
        new_identifiers = set(EditTypeInferrer._extract_identifiers(new_line))
        old_identifiers = set(EditTypeInferrer._extract_identifiers(old_line))
        
        added = new_identifiers - old_identifiers
        removed = old_identifiers - new_identifiers
        
        if len(added) == 1 and len(removed) == 1:
            return 'identifier_rename'
        
        # Check for operator change
        new_ops = set(EditTypeInferrer._extract_operators(new_line))
        old_ops = set(EditTypeInferrer._extract_operators(old_line))
        
        if new_ops != old_ops:
            return 'operator_change'
        
        # Check for literal change
        try:
            old_tree = ast.parse(old_line.strip())
            if EditTypeInferrer._literals_changed(tree, old_tree):
                return 'literal_change'
        except:
            pass
        
        # Check for function call changes
        if 'def ' in new_line or 'def ' in old_line:
            return 'function_def_edit'
        
        # Default to generic statement edit
        return 'python_statement_edit'
    
    @staticmethod
    def _extract_identifiers(line: str) -> List[str]:
        """Extract Python identifiers from a line"""
        try:
            tree = ast.parse(line.strip())
            identifiers = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    identifiers.append(node.id)
            return identifiers
        except:
            return []
    
    @staticmethod
    def _extract_operators(line: str) -> List[str]:
        """Extract operators from a line"""
        operators = []
        op_chars = {'+', '-', '*', '/', '%', '**', '//', '<', '>', '<=', '>=', '==', '!='}
        for op in op_chars:
            if op in line:
                operators.append(op)
        return operators
    
    @staticmethod
    def _literals_changed(tree1: ast.AST, tree2: ast.AST) -> bool:
        """Check if literals changed between two ASTs"""
        literals1 = []
        literals2 = []
        
        for node in ast.walk(tree1):
            if isinstance(node, ast.Constant):
                literals1.append(node.value)
        
        for node in ast.walk(tree2):
            if isinstance(node, ast.Constant):
                literals2.append(node.value)
        
        return literals1 != literals2


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
            nodes: IntentNode list for node type analysis
        """
        # Keep both the original list and a fast lookup dict for mappings
        self.mapping_list: List[Mapping] = mappings
        self.mappings: dict[str, Mapping] = {m.node_id: m for m in mappings}
        self.generator = generator
        self.direct_ops = DirectEditOperations()
        self.config = config or DEFAULT_CONFIG
        # IntentNode list used to locate affected nodes for an edit
        self.nodes = nodes or []
        self.edit_inferrer = EditTypeInferrer()

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

        Simplified routing strategy:
        1. Infer edit type if not provided
        2. Check edited line type:
           - Complete Python statement → direct edit
           - Python with holes/incomplete → direct edit (may need regeneration)
           - NL/hole content → LLM generation
        
        Args:
            edit: The edit made to semiformal code
            semiformal_code: Current semiformal code
            python_code: Current Python code

        Returns:
            EditResult with updated Python code
        """
        # Step 1: Infer edit type if not provided
        if not edit.type:
            semiformal_lines = semiformal_code.split('\n')
            current_line = (
                semiformal_lines[edit.line]
                if edit.line is not None and 0 <= edit.line < len(semiformal_lines)
                else edit.content
            )
            old_line = edit.old_content if edit.old_content else None

            edit.type = self.edit_inferrer.infer_edit_type(edit, current_line, old_line)
        
        print(f"[EditTranslator] Edit type: {edit.type}")
        
        # Step 2: Route based on edit type
        # Python statement edits → try direct edit first
        if edit.type in ('python_statement_edit', 'python_assignment_edit', 'python_expression_edit',
                          'identifier_rename', 'operator_change', 'literal_change', 'python_function_def_edit'):
            result = self._direct_translate(edit, python_code)
            if result.success:
                return result
            # If direct edit fails, fall back to regeneration
            print(f"[EditTranslator] Direct edit failed, falling back to LLM regeneration")
        
        # NL/hole edits or failed direct edits → use LLM regeneration
        return self._llm_translate(edit, semiformal_code, python_code)

    def _is_direct_translatable(self, edit: Edit) -> bool:
        """
        Check if edit can be directly mapped to Python.

        Phase 1: Direct edits (36.6% from EDIT_MAPPING_TABLE.md)
        Uses configuration instead of hardcoded list.
        """
        return edit.type in self.config.edit_types.direct_edit_types

    def _resolve_python_line(self, edit: Edit, python_code: str) -> int:
        """
        Resolve the Python line number that should be edited for a given semiformal edit.

        We *do not* assume that semiformal line numbers match Python line numbers.
        Instead, we:
          1. Find affected intent nodes in the IR
          2. Look up their Mapping.slices[0].line_start to get the corresponding
             Python line (1-based from mapping, convert to 0-based)
        """
        # If we don't have nodes or mappings, fall back to the raw edit.line
        if not self.nodes or not self.mappings:
            return edit.line or 0

        affected_nodes = self._get_affected_nodes(edit)
        best_line: Optional[int] = None

        # Prefer expression / statement-like nodes on the edited line
        preferred_types = {'expr_stmt', 'function_call', 'identifier', 'nl_phrase', 'hole'}

        for node in affected_nodes:
            mapping = self.mappings.get(getattr(node, "id", ""), None)
            if not mapping or not mapping.slices:
                continue

            py_line_1_based = mapping.slices[0].line_start
            if py_line_1_based <= 0:
                continue

            py_line_0_based = py_line_1_based - 1

            if best_line is None:
                best_line = py_line_0_based

            # If this node type is more statement-like, prefer its line
            if getattr(node, "type", "") in preferred_types:
                best_line = py_line_0_based
                break

        # Fallback: use the original edit.line if mapping-based resolution failed
        if best_line is None:
            return edit.line or 0

        # Clamp to valid range (defensive)
        total_lines = len(python_code.split('\n'))
        if best_line < 0:
            return 0
        if best_line >= total_lines:
            return max(0, total_lines - 1)

        return best_line

    def _direct_translate(self, edit: Edit, python_code: str) -> EditResult:
        """
        Translate using direct AST manipulation or line replacement.
        
        Strategy:
        - For identified edit types (rename, operator, literal): use specific operations
        - For generic Python statement edits: replace the entire line
        """
        # Compute the Python line to operate on for line-based edits
        target_line = self._resolve_python_line(edit, python_code) if edit.line is not None else None

        # Specific edit types with dedicated operations
        if edit.type == 'identifier_rename':
            return self.direct_ops.rename_identifier(
                python_code,
                edit.old_content or edit.location,
                edit.content
            )

        elif edit.type == 'operator_change':
            return self.direct_ops.change_operator(
                python_code,
                target_line or 0,
                edit.old_content or '',
                edit.content
            )

        elif edit.type == 'literal_change':
            return self.direct_ops.change_literal(
                python_code,
                target_line or 0,
                edit.old_content,
                edit.content
            )
        
        # Generic Python statement edit - replace the line directly
        elif edit.type in ('python_statement_edit', 'python_assignment_edit', 
                           'python_expression_edit', 'python_function_def_edit'):
            if target_line is not None:
                return self.direct_ops.replace_statement(
                    python_code,
                    target_line,
                    edit.content
                )
        
        # Unsupported edit type for direct translation
        return EditResult(
            success=False,
            new_code=python_code,
            message=f"Cannot directly translate edit type: {edit.type}"
        )

    def _llm_translate(
        self,
        edit: Edit,
        semiformal_code: str,
        python_code: str
    ) -> EditResult:
        """
        Translate using LLM for complex semantic changes.
        
        Uses single LLM call with diff format generation, but focuses the prompt
        on the nodes/regions actually touched by the edit.
        """
        # Re-parse semiformal code to get updated nodes (AFTER the edit)
        try:
            from parser import SemiformalParser
            parser = SemiformalParser()
            nodes = parser.parse(semiformal_code)
        except Exception:
            # Fallback: mark for regeneration
            return EditResult(
                success=True,
                new_code=python_code,
                message=f"LLM translation for '{edit.type}' requires regeneration",
                needs_regeneration=True,
                regeneration_targets=[edit.location]
            )

        # Compute a focused set of nodes affected by this edit in the *new* IR.
        # We primarily use the line number, falling back to simple content match.
        focus_nodes = []
        if edit.line is not None:
            for node in nodes:
                if hasattr(node, "span") and node.span:
                    if node.span[0] <= edit.line <= node.span[1]:
                        focus_nodes.append(node)

        if not focus_nodes and edit.content:
            content_str = str(edit.content).strip()
            for node in nodes:
                if getattr(node, "content", "") == content_str:
                    focus_nodes.append(node)

        # Determine a coarse trigger type to help the LLM understand context.
        # We no longer rely on completeness classification here; instead we use
        # simple heuristics based on the inferred edit type.
        trigger_type = "semiformal_llm_edit"
        if edit.type:
            et = edit.type.lower()
            if "python" in et:
                trigger_type = "complete_python_edit"
            elif "hole" in et or "nl" in et:
                trigger_type = "nl_or_hole_edit"

        # Thread the previous semiformal spec through to the generator/LLM so
        # prompts can show a before/after view when available.
        previous_semiformal = edit.metadata.get("previous_semiformal_code", "")

        # Use single LLM call with existing Python code (diff mode), telling the
        # generator which nodes to focus on.
        new_code, mappings = self.generator.generate_with_mapping(
            nodes=nodes,
            context=semiformal_code,
            existing_python=python_code,  # Pass existing code for diff generation
            focus_nodes=focus_nodes or None,
            trigger_type=trigger_type,
            previous_semiformal=previous_semiformal,
        )

        # Refresh internal mapping table and node list so future edits see the
        # updated layout. Keep both list and dict variants in sync.
        self.mapping_list = mappings
        self.mappings = {m.node_id: m for m in mappings}
        self.nodes = nodes

        return EditResult(
            success=True,
            new_code=new_code,
            message=f"Generated code using LLM for '{edit.type}'",
            new_nodes=nodes,
            new_mappings=mappings,
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
        # Treat generic Python-side line edits as transient by default
        if edit.metadata.get("from_side") == "python":
            return False, "none"

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
