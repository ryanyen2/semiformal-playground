"""
Node classification for robust bidirectional mapping.

Classifies IR nodes into DIRECT, HYBRID, or NL categories based on
their completeness and Python validity.
"""

import ast
import keyword
from typing import Set, Optional
from ir import IRNode, NodeType, ProgramIR, NodeStatus
from mapping_types import MappingCategory


class NodeClassifier:
    """
    Classifies IR nodes to determine appropriate mapping strategy.

    Classification determines how edits are handled:
    - DIRECT: Direct AST manipulation, no LLM needed
    - HYBRID: Usage direct, definition needs LLM
    - NL: Full regeneration with LLM
    """

    # Python built-in functions that don't need definition
    BUILTINS = {
        'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set',
        'tuple', 'bool', 'type', 'isinstance', 'hasattr', 'getattr', 'setattr',
        'min', 'max', 'sum', 'abs', 'round', 'sorted', 'reversed', 'enumerate',
        'zip', 'map', 'filter', 'open', 'input', 'repr', 'chr', 'ord',
        'any', 'all', 'callable', 'dir', 'help', 'id', 'iter', 'next',
    }

    def __init__(self, ir: ProgramIR):
        self.ir = ir
        self.defined_names: Set[str] = set()
        self._build_defined_names()

    def _build_defined_names(self):
        """Build set of all defined names in IR."""
        self.defined_names = set(self.BUILTINS)

        # Add all function definitions
        for node in self.ir.nodes.values():
            if node.node_type == NodeType.FUNCTION_DEF:
                self.defined_names.add(node.name)

        # Add all variable assignments
        for node in self.ir.nodes.values():
            if node.node_type == NodeType.VARIABLE_ASSIGN:
                self.defined_names.add(node.name)
                # Also add LHS variables
                lhs = node.metadata.get('lhs', [])
                for var in lhs:
                    self.defined_names.add(var)

    def classify(self, node: IRNode) -> MappingCategory:
        """
        Classify a node into DIRECT, HYBRID, or NL.

        Decision tree:
        1. Check if natural language → NL
        2. Check if valid Python syntax → proceed
        3. Check completeness:
           - All references defined → DIRECT
           - Some references undefined → HYBRID
        4. Default → NL
        """

        # Step 1: Check for natural language
        if self._is_natural_language(node):
            return MappingCategory.NL

        # Step 2: Check if valid Python
        if not self._is_valid_python(node):
            return MappingCategory.NL

        # Step 3: Check completeness based on node type
        if node.node_type == NodeType.FUNCTION_CALL:
            return self._classify_function_call(node)

        elif node.node_type == NodeType.VARIABLE_ASSIGN:
            return self._classify_variable_assign(node)

        elif node.node_type == NodeType.FUNCTION_DEF:
            return self._classify_function_def(node)

        elif node.node_type == NodeType.STATEMENT:
            return self._classify_statement(node)

        # Default: treat as NL if uncertain
        return MappingCategory.NL

    def _is_natural_language(self, node: IRNode) -> bool:
        """
        Check if node is primarily natural language.

        Heuristics:
        - Marked as NL_EXPRESSION type
        - Contains many English words without Python syntax
        - No valid AST and contains prose-like content
        """
        # Explicit NL type
        if node.node_type == NodeType.NL_EXPRESSION:
            return True

        # If we have a valid AST, it's not pure NL
        # (it might be incomplete Python, but not NL)
        if node.spec_ast is not None:
            return False

        # No AST - check if it looks like English prose
        text = node.spec_text.strip()

        # Check for common NL patterns
        nl_patterns = [
            ' and ', ' or ', ' the ', ' a ', ' an ',
            'load', 'preprocess', 'split', 'transform',
            'into', 'from', 'with', 'using'
        ]

        pattern_count = sum(1 for pattern in nl_patterns if pattern in text.lower())

        # Check for Python operators
        python_ops = ['=', '(', ')', '[', ']', '{', '}', ',', ':', ';']
        has_python_syntax = any(op in text for op in python_ops)

        # If has NL patterns and no Python syntax → likely NL
        if pattern_count >= 2 and not has_python_syntax:
            return True

        # Count words that look like identifiers vs prose
        words = [w for w in text.split() if w.isalpha()]
        if len(words) >= 3:
            # Many words without Python syntax → likely NL
            return not has_python_syntax

        return False

    def _is_valid_python(self, node: IRNode) -> bool:
        """Check if node has valid Python AST."""
        return node.spec_ast is not None

    def _classify_function_call(self, node: IRNode) -> MappingCategory:
        """
        Classify a function call node.

        DIRECT: Function is defined (builtin or in IR)
        HYBRID: Function is not defined (needs generation)
        """
        func_name = node.name

        # Check if function is defined
        if func_name in self.defined_names:
            # Function is defined → call is direct
            return MappingCategory.DIRECT

        # Function not defined → hybrid (call is direct, definition needs gen)
        return MappingCategory.HYBRID

    def _classify_variable_assign(self, node: IRNode) -> MappingCategory:
        """
        Classify a variable assignment node.

        DIRECT: RHS is concrete value or defined reference
        HYBRID: RHS is ellipsis or undefined reference
        NL: RHS is natural language
        """
        # Check RHS from metadata
        rhs = node.metadata.get('rhs', '')

        # Ellipsis placeholder → hybrid
        if rhs == '...' or rhs == 'Ellipsis':
            return MappingCategory.HYBRID

        # Try to parse RHS
        try:
            rhs_ast = ast.parse(rhs, mode='eval')
        except:
            # Can't parse → likely NL
            return MappingCategory.NL

        # Check if RHS contains undefined references
        if self._has_undefined_references(rhs_ast):
            return MappingCategory.HYBRID

        # RHS is concrete → direct
        return MappingCategory.DIRECT

    def _classify_function_def(self, node: IRNode) -> MappingCategory:
        """
        Classify a function definition node.

        DIRECT: Body is complete Python code
        HYBRID: Body contains only pass/... or is empty
        """
        # Check if body is incomplete
        if node.spec_ast and isinstance(node.spec_ast, ast.FunctionDef):
            body = node.spec_ast.body

            # Empty body → hybrid
            if not body:
                return MappingCategory.HYBRID

            # Only pass or ellipsis → hybrid
            if len(body) == 1:
                stmt = body[0]
                if isinstance(stmt, ast.Pass):
                    return MappingCategory.HYBRID
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    if stmt.value.value == Ellipsis or stmt.value.value == '...':
                        return MappingCategory.HYBRID

            # Check if body has undefined references
            if self._has_undefined_references(node.spec_ast):
                return MappingCategory.HYBRID

        # Complete function → direct
        return MappingCategory.DIRECT

    def _classify_statement(self, node: IRNode) -> MappingCategory:
        """
        Classify a generic statement node.

        Check if all references are defined.
        """
        if not node.spec_ast:
            return MappingCategory.NL

        if self._has_undefined_references(node.spec_ast):
            return MappingCategory.HYBRID

        return MappingCategory.DIRECT

    def _has_undefined_references(self, tree: ast.AST) -> bool:
        """
        Check if AST contains references to undefined names.

        Returns True if there are undefined function calls or variable refs.
        """
        undefined_found = False

        class UndefinedChecker(ast.NodeVisitor):
            def __init__(checker_self, defined: Set[str]):
                checker_self.defined = defined
                checker_self.undefined_found = False

            def visit_Name(checker_self, node: ast.Name):
                if isinstance(node.ctx, ast.Load):
                    if node.id not in checker_self.defined:
                        checker_self.undefined_found = True
                checker_self.generic_visit(node)

            def visit_Call(checker_self, node: ast.Call):
                # Check function name
                if isinstance(node.func, ast.Name):
                    if node.func.id not in checker_self.defined:
                        checker_self.undefined_found = True
                checker_self.generic_visit(node)

        checker = UndefinedChecker(self.defined_names)
        checker.visit(tree)
        return checker.undefined_found

    def classify_all(self) -> dict[str, MappingCategory]:
        """
        Classify all nodes in IR.

        Returns:
            Dictionary mapping node IDs to categories
        """
        categories = {}
        for node_id, node in self.ir.nodes.items():
            categories[node_id] = self.classify(node)
        return categories

    def update_for_new_node(self, node: IRNode) -> MappingCategory:
        """
        Classify a newly added node and update defined names.

        This is used during incremental parsing when new nodes are added.
        """
        # First classify the node
        category = self.classify(node)

        # Then add to defined names if it's a definition
        if node.node_type == NodeType.FUNCTION_DEF:
            self.defined_names.add(node.name)
        elif node.node_type == NodeType.VARIABLE_ASSIGN:
            self.defined_names.add(node.name)
            lhs = node.metadata.get('lhs', [])
            for var in lhs:
                self.defined_names.add(var)

        return category


def classify_edit_type(old_node: IRNode, new_node: IRNode) -> tuple[str, dict]:
    """
    Classify the type of edit between old and new node.

    Returns:
        (EditType, metadata dict)
    """
    from backend.mapping_types import EditType

    # Check what changed
    text_changed = old_node.spec_text != new_node.spec_text
    signature_changed = old_node.spec_signature != new_node.spec_signature

    if not text_changed and not signature_changed:
        return EditType.UNKNOWN, {}

    # Check LHS change (for assignments)
    old_lhs = old_node.metadata.get('lhs', [])
    new_lhs = new_node.metadata.get('lhs', [])
    if old_lhs != new_lhs:
        return EditType.STRUCTURAL, {
            'old_lhs': old_lhs,
            'new_lhs': new_lhs,
            'change': 'lhs'
        }

    # Check RHS change (for assignments)
    old_rhs = old_node.metadata.get('rhs', '')
    new_rhs = new_node.metadata.get('rhs', '')
    if old_rhs != new_rhs:
        # Determine if structural or value change
        if _is_structural_rhs_change(old_rhs, new_rhs):
            return EditType.STRUCTURAL, {
                'old_rhs': old_rhs,
                'new_rhs': new_rhs,
                'change': 'rhs'
            }
        else:
            return EditType.VALUE, {
                'old_value': old_rhs,
                'new_value': new_rhs
            }

    # Check signature change (for functions)
    if signature_changed:
        return EditType.SIGNATURE, {
            'old_signature': old_node.spec_signature,
            'new_signature': new_node.spec_signature
        }

    # Check if semantic change (NL content)
    if text_changed:
        # If primarily NL, it's semantic change
        # Otherwise, might be value or structural
        old_is_nl = old_node.node_type == NodeType.NL_EXPRESSION
        new_is_nl = new_node.node_type == NodeType.NL_EXPRESSION

        if old_is_nl or new_is_nl:
            return EditType.SEMANTIC, {
                'old_text': old_node.spec_text,
                'new_text': new_node.spec_text
            }

    # Default: unknown/general change
    return EditType.UNKNOWN, {}


def _is_structural_rhs_change(old_rhs: str, new_rhs: str) -> bool:
    """
    Determine if RHS change is structural vs value.

    Structural: tuple/list structure change
    Value: literal value change
    """
    # Check for tuple/list structure
    old_is_structured = any(c in old_rhs for c in ['(', ')', '[', ']', ','])
    new_is_structured = any(c in new_rhs for c in ['(', ')', '[', ']', ','])

    if old_is_structured != new_is_structured:
        return True

    # Check for function call change
    old_has_call = '(' in old_rhs and ')' in old_rhs
    new_has_call = '(' in new_rhs and ')' in new_rhs

    if old_has_call or new_has_call:
        return True

    return False
