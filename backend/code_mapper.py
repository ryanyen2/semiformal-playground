"""
Robust code mapping algorithm for semiformal->code node mapping.

This module implements an AST-based mapping algorithm that handles:
- Multiple implementations of the same variable
- Context awareness (module-level vs inside functions)
- Dependency matching
- One-to-many mappings (one semiformal line -> multiple generated statements)
- Execution order preferences
"""

import ast
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass

from ir import IRNode, NodeType


@dataclass
class CodeStatement:
    """Represents a statement in generated code with metadata."""
    ast_node: ast.AST
    line_num: int
    text: str
    is_module_level: bool  # True if at module level, False if inside function
    assigned_vars: Set[str]  # Variables assigned by this statement
    referenced_vars: Set[str]  # Variables referenced in RHS
    execution_order: int  # Order in which this executes (module-level statements only)


class ASTCodeMapper:
    """
    Maps semiformal IR nodes to generated code using AST-based analysis.

    Key improvements over simple text matching:
    1. Understands code structure (module-level vs function-level)
    2. Handles multiple implementations (prefers last/best match)
    3. Matches based on dependencies (RHS variables)
    4. Supports one-to-many mappings
    5. Uses execution order to disambiguate
    """

    def __init__(self):
        self.code_tree: Optional[ast.Module] = None
        self.statements: List[CodeStatement] = []
        self.module_level_statements: List[CodeStatement] = []

    def parse_generated_code(self, code: str) -> None:
        """Parse generated code and extract structured information."""
        try:
            self.code_tree = ast.parse(code)
        except SyntaxError as e:
            print(f"Warning: Generated code has syntax errors: {e}")
            self.code_tree = None
            return

        # Extract all statements with metadata
        self.statements = []
        self.module_level_statements = []

        # Process module-level statements
        exec_order = 0
        for node in self.code_tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Skip imports for execution order
                continue

            stmt = self._analyze_statement(node, is_module_level=True, execution_order=exec_order)
            if stmt:
                self.statements.append(stmt)
                self.module_level_statements.append(stmt)
                exec_order += 1

            # Also extract statements inside function definitions
            if isinstance(node, ast.FunctionDef):
                for func_stmt in node.body:
                    func_stmt_obj = self._analyze_statement(func_stmt, is_module_level=False, execution_order=-1)
                    if func_stmt_obj:
                        self.statements.append(func_stmt_obj)

    def _analyze_statement(
        self,
        node: ast.AST,
        is_module_level: bool,
        execution_order: int
    ) -> Optional[CodeStatement]:
        """Analyze a statement and extract metadata."""
        if not hasattr(node, 'lineno'):
            return None

        # Get text representation
        try:
            text = ast.unparse(node)
        except:
            text = ""

        # Extract assigned variables
        assigned_vars = set()
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assigned_vars.update(self._extract_names_from_target(target))
        elif isinstance(node, ast.AugAssign):
            assigned_vars.update(self._extract_names_from_target(node.target))
        elif isinstance(node, ast.AnnAssign):
            assigned_vars.update(self._extract_names_from_target(node.target))
        elif isinstance(node, ast.FunctionDef):
            assigned_vars.add(node.name)

        # Extract referenced variables (from RHS)
        referenced_vars = set()
        if isinstance(node, ast.Assign):
            referenced_vars.update(self._extract_names_from_expr(node.value))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            referenced_vars.update(self._extract_names_from_expr(node.value))
        elif isinstance(node, ast.Expr):
            referenced_vars.update(self._extract_names_from_expr(node.value))

        return CodeStatement(
            ast_node=node,
            line_num=node.lineno,
            text=text,
            is_module_level=is_module_level,
            assigned_vars=assigned_vars,
            referenced_vars=referenced_vars,
            execution_order=execution_order if is_module_level else -1
        )

    def _extract_names_from_target(self, node: ast.AST) -> Set[str]:
        """Extract variable names from assignment target."""
        names = set()
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                names.update(self._extract_names_from_target(elt))
        elif isinstance(node, ast.List):
            for elt in node.elts:
                names.update(self._extract_names_from_target(elt))
        return names

    def _extract_names_from_expr(self, node: ast.AST) -> Set[str]:
        """Extract variable names referenced in expression."""
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
        return names

    def map_node_to_code(self, ir_node: IRNode) -> Optional[str]:
        """
        Map an IR node to its corresponding code in the generated output.

        Returns the code text that implements this IR node, or None if not found.
        """
        node_type_val = ir_node.node_type.value

        if node_type_val in ('function_def', 'function_call'):
            return self._map_function(ir_node)
        elif node_type_val in ('variable_assign', 'nl_expression'):
            return self._map_variable(ir_node)
        else:
            return None

    def _map_function(self, ir_node: IRNode) -> Optional[str]:
        """Map a function node to its definition in generated code."""
        func_name = ir_node.name

        # Find function definition
        for stmt in self.statements:
            if isinstance(stmt.ast_node, ast.FunctionDef):
                if stmt.ast_node.name == func_name:
                    # Extract complete function (including body)
                    return self._extract_function_text(stmt.ast_node)

        return None

    def _extract_function_text(self, func_node: ast.FunctionDef) -> str:
        """Extract complete function definition as text."""
        # Use unparse to get the complete function
        try:
            return ast.unparse(func_node)
        except:
            return ""

    def _map_variable(self, ir_node: IRNode) -> Optional[str]:
        """
        Map a variable assignment to generated code.

        Strategy:
        1. Find all module-level assignments to this variable
        2. Filter by dependency matching (check RHS references)
        3. Prefer the LAST match (execution order)
        4. Handle tuple unpacking (x, y = ...)
        """
        var_name = ir_node.name

        # Get expected dependencies from spec
        expected_deps = self._extract_dependencies_from_spec(ir_node)

        # Find all candidates (module-level assignments to this variable)
        candidates = []
        for stmt in self.module_level_statements:
            # Check if this statement assigns to our variable
            if var_name in stmt.assigned_vars:
                # Score this candidate based on dependency match
                score = self._score_dependency_match(stmt.referenced_vars, expected_deps)
                candidates.append((stmt, score))

        if not candidates:
            return None

        # Sort by score (descending), then by execution order (descending = prefer later)
        candidates.sort(key=lambda x: (x[1], x[0].execution_order), reverse=True)

        # Return the best match
        best_stmt = candidates[0][0]
        return best_stmt.text

    def _extract_dependencies_from_spec(self, ir_node: IRNode) -> Set[str]:
        """
        Extract variables that should be referenced in the RHS from the spec.

        For example:
        - "output = transform(result)" -> expects 'transform' and 'result'
        - "x, y = {split data}" -> no specific dependencies from this syntax
        """
        deps = set()

        # Parse spec_text to extract variable references
        spec = ir_node.spec_text
        if '=' in spec:
            rhs = spec.split('=', 1)[1].strip()

            # Remove curly braces (NL markers)
            rhs = rhs.replace('{', '').replace('}', '')

            # Try to extract identifiers
            # This is a simple heuristic - could use AST if spec is valid Python
            import re
            # Find words that look like identifiers
            identifiers = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', rhs)

            # Filter out common keywords and NL words
            keywords = {'and', 'or', 'not', 'in', 'is', 'the', 'a', 'an', 'to', 'of',
                       'split', 'data', 'into', 'load', 'process', 'dataset', 'from'}
            for ident in identifiers:
                if ident.lower() not in keywords and not ident.startswith('_'):
                    deps.add(ident)

        return deps

    def _score_dependency_match(self, actual_deps: Set[str], expected_deps: Set[str]) -> float:
        """
        Score how well actual dependencies match expected dependencies.

        Returns a score where higher is better.
        """
        if not expected_deps:
            # If no expected dependencies, all matches are equal
            # Return 0 so execution order becomes the tiebreaker
            return 0.0

        # Compute overlap
        intersection = actual_deps & expected_deps
        union = actual_deps | expected_deps

        if not union:
            return 0.0

        # Jaccard similarity
        score = len(intersection) / len(union)

        # Bonus for exact match
        if actual_deps == expected_deps:
            score += 1.0

        # Bonus for having all expected deps (even if there are extra)
        if expected_deps.issubset(actual_deps):
            score += 0.5

        return score


def extract_implementations_robust(
    generated_code: str,
    incomplete_nodes: List[IRNode]
) -> Dict[str, str]:
    """
    Extract implementations using robust AST-based mapping.

    Args:
        generated_code: Complete generated code
        incomplete_nodes: List of IR nodes that need mapping

    Returns:
        Dictionary mapping node IDs to their implementations
    """
    mapper = ASTCodeMapper()
    mapper.parse_generated_code(generated_code)

    implementations = {}

    for node in incomplete_nodes:
        impl = mapper.map_node_to_code(node)
        if impl:
            implementations[node.id] = impl

    return implementations
