"""
Robust bidirectional mapping between IR and Python AST.

Implements the mapping algorithm from ROBUST_MAPPING_DESIGN.md.
"""

import ast
from typing import List, Dict, Set, Optional, Tuple
from ir import IRNode, ProgramIR, NodeType
from mapping_types import (
    MappingCategory, IRToPythonMapping, PythonToIRMapping,
    BidirectionalMapping, HybridMapping, NLMapping, UnderspecNode,
    enumerate_ast_paths, get_parent_path
)
from node_classifier import NodeClassifier


class RobustMapper:
    """
    Builds and maintains robust bidirectional mapping between IR and Python AST.

    This mapper handles three categories of nodes:
    - DIRECT: 1:1 mapping
    - HYBRID: Split mapping (usage + definition)
    - NL: Many-to-many mapping (NL phrase → multiple statements)
    """

    def __init__(self):
        self.classifier: Optional[NodeClassifier] = None

    def build_mapping(self, ir: ProgramIR, code: str) -> BidirectionalMapping:
        """
        Build complete bidirectional mapping between IR and Python code.

        Args:
            ir: Program IR with spec information
            code: Generated Python code string

        Returns:
            BidirectionalMapping with forward and reverse mappings
        """
        # Parse code to AST
        try:
            code_ast = ast.parse(code)
        except SyntaxError:
            # If code doesn't parse, return empty mapping
            return BidirectionalMapping(
                forward=IRToPythonMapping(),
                reverse=PythonToIRMapping()
            )

        # Initialize classifier
        self.classifier = NodeClassifier(ir)

        # Initialize mappings
        forward = IRToPythonMapping()
        reverse = PythonToIRMapping()

        # Classify all nodes
        categories = self.classifier.classify_all()

        # Build line-to-AST index for fast lookup
        ast_by_line = self._build_line_index(code_ast)

        # Map nodes in topological order (dependencies first)
        sorted_nodes = self._topological_sort(ir)

        for node in sorted_nodes:
            category = categories[node.id]

            if category == MappingCategory.DIRECT:
                self._map_direct_node(node, code_ast, ast_by_line, forward, reverse)

            elif category == MappingCategory.HYBRID:
                self._map_hybrid_node(node, code_ast, ast_by_line, forward, reverse, ir)

            elif category == MappingCategory.NL:
                self._map_nl_node(node, code_ast, ast_by_line, forward, reverse)

        # Detect underspecification
        underspec = self._detect_underspecification(code_ast, reverse)

        return BidirectionalMapping(
            forward=forward,
            reverse=reverse,
            underspec_nodes=underspec
        )

    def _build_line_index(self, code_ast: ast.Module) -> Dict[int, List[ast.stmt]]:
        """
        Build index of AST statements by line number.

        Returns:
            Dictionary mapping line numbers to statements starting on that line
        """
        index = {}
        for stmt in ast.walk(code_ast):
            if isinstance(stmt, ast.stmt) and hasattr(stmt, 'lineno'):
                line = stmt.lineno
                if line not in index:
                    index[line] = []
                index[line].append(stmt)
        return index

    def _topological_sort(self, ir: ProgramIR) -> List[IRNode]:
        """
        Sort nodes in topological order (dependencies first).

        This ensures we process definitions before usages.
        """
        # Simple approach: function defs first, then statements
        functions = []
        statements = []

        for node in ir.nodes.values():
            if node.node_type == NodeType.FUNCTION_DEF:
                functions.append(node)
            else:
                statements.append(node)

        # Sort by line number within each category
        functions.sort(key=lambda n: n.spec_location.line if n.spec_location else 0)
        statements.sort(key=lambda n: n.spec_location.line if n.spec_location else 0)

        return functions + statements

    def _map_direct_node(
        self,
        node: IRNode,
        code_ast: ast.Module,
        ast_by_line: Dict[int, List[ast.stmt]],
        forward: IRToPythonMapping,
        reverse: PythonToIRMapping
    ):
        """
        Map a DIRECT node (1:1 mapping to Python AST).

        Strategy:
        1. Use code_location line number to find AST node
        2. Match by signature/name if needed
        3. Create single mapping
        """
        # Get code location
        if not node.code_location:
            # Try spec location as fallback
            if not node.spec_location:
                return
            line = node.spec_location.line
        else:
            line = node.code_location.line

        # Find AST node at this line
        candidates = ast_by_line.get(line, [])

        if not candidates:
            # No AST at this line - might be shifted
            # Try nearby lines
            for offset in range(-2, 3):
                candidates = ast_by_line.get(line + offset, [])
                if candidates:
                    break

        if not candidates:
            return

        # Match by type and name
        matched_stmt = None
        for stmt in candidates:
            if self._matches_node(stmt, node):
                matched_stmt = stmt
                break

        if not matched_stmt:
            # Use first candidate
            matched_stmt = candidates[0]

        # Compute AST path
        ast_path = self._compute_path(matched_stmt, code_ast)

        # Add mapping
        forward.add_direct_mapping(node.id, ast_path)
        reverse.add_mapping(ast_path, node.id, is_generated=False)

    def _map_hybrid_node(
        self,
        node: IRNode,
        code_ast: ast.Module,
        ast_by_line: Dict[int, List[ast.stmt]],
        forward: IRToPythonMapping,
        reverse: PythonToIRMapping,
        ir: ProgramIR
    ):
        """
        Map a HYBRID node (split mapping: usage + definition).

        Example: `result = process_data(input)` where process_data is undefined
        - Usage: the call expression at spec line
        - Definition: the generated function definition elsewhere
        """
        mapping = HybridMapping()

        # 1. Map usage (call site, variable reference, etc.)
        if node.code_location:
            line = node.code_location.line
            candidates = ast_by_line.get(line, [])

            for stmt in candidates:
                if self._matches_node(stmt, node):
                    usage_path = self._compute_path(stmt, code_ast)
                    mapping.usage_ast_paths.append(usage_path)
                    mapping.usage_ast_nodes.append(stmt)
                    reverse.add_mapping(usage_path, node.id, is_generated=False)
                    break

        # 2. Map definition (generated function, implementation, etc.)
        # Look for function definition with matching name
        if node.node_type == NodeType.FUNCTION_CALL:
            # Find function definition in code
            func_name = node.name
            for stmt in ast.walk(code_ast):
                if isinstance(stmt, ast.FunctionDef) and stmt.name == func_name:
                    def_path = self._compute_path(stmt, code_ast)
                    mapping.definition_ast_paths.append(def_path)
                    mapping.definition_ast_nodes.append(stmt)
                    reverse.add_mapping(def_path, node.id, is_generated=True)
                    break

        # Add to forward mapping
        forward.add_hybrid_mapping(node.id, mapping)

    def _map_nl_node(
        self,
        node: IRNode,
        code_ast: ast.Module,
        ast_by_line: Dict[int, List[ast.stmt]],
        forward: IRToPythonMapping,
        reverse: PythonToIRMapping
    ):
        """
        Map an NL node (many-to-many mapping).

        Natural language might generate multiple Python statements.
        We need to identify the entire generated subtree.

        Strategy:
        1. Use code_location line span to identify generated region
        2. Extract all AST nodes in that region
        3. Use semantic anchors (variable names) for validation
        """
        mapping = NLMapping()

        # Get generated code span from node
        if node.code_location:
            start_line = node.code_location.line
            end_line = node.code_location.end_line or start_line
            mapping.generated_code_span = (start_line, end_line)

            # Extract all statements in this span
            for line in range(start_line, end_line + 1):
                statements = ast_by_line.get(line, [])
                for stmt in statements:
                    path = self._compute_path(stmt, code_ast)
                    if path not in mapping.subtree_root_paths:
                        mapping.subtree_root_paths.append(path)
                        mapping.subtree_ast_nodes.append(stmt)
                        reverse.add_mapping(path, node.id, is_generated=True)

        # Extract semantic anchors (variable names in spec)
        # These help with fuzzy matching later
        if node.metadata.get('lhs'):
            mapping.semantic_anchors.extend(node.metadata['lhs'])

        # Add to forward mapping
        forward.add_nl_mapping(node.id, mapping)

    def _matches_node(self, stmt: ast.stmt, node: IRNode) -> bool:
        """
        Check if an AST statement matches an IR node.

        Matching criteria:
        - Type correspondence (FunctionDef ↔ FUNCTION_DEF, etc.)
        - Name matching
        - Signature matching
        """
        if node.node_type == NodeType.FUNCTION_DEF:
            return isinstance(stmt, ast.FunctionDef) and stmt.name == node.name

        elif node.node_type == NodeType.FUNCTION_CALL:
            # Look for expression statement with call
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Name):
                    return stmt.value.func.id == node.name
            # Or assignment with call on RHS
            if isinstance(stmt, ast.Assign):
                if isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        return stmt.value.func.id == node.name

        elif node.node_type == NodeType.VARIABLE_ASSIGN:
            if isinstance(stmt, ast.Assign):
                # Match by LHS variable name
                lhs = node.metadata.get('lhs', [])
                if lhs:
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == lhs[0]:
                            return True
                        # Tuple unpacking
                        if isinstance(target, ast.Tuple):
                            target_names = [n.id for n in target.elts if isinstance(n, ast.Name)]
                            if target_names == lhs:
                                return True

        return False

    def _compute_path(self, node: ast.AST, root: ast.Module) -> str:
        """
        Compute the path string for an AST node relative to root.

        This is a simplified version - in production, we'd traverse from root.
        For now, we use a heuristic based on position.
        """
        # Try to find node in root.body
        if node in root.body:
            idx = root.body.index(node)
            return f"body[{idx}]"

        # For nested nodes, we'd need full traversal
        # For now, use line number as approximation
        if hasattr(node, 'lineno'):
            # Find in body by line number
            for i, stmt in enumerate(root.body):
                if hasattr(stmt, 'lineno') and stmt.lineno == node.lineno:
                    return f"body[{i}]"

        # Fallback: use a placeholder
        return f"unknown_{id(node)}"

    def _detect_underspecification(
        self,
        code_ast: ast.Module,
        reverse: PythonToIRMapping
    ) -> List[UnderspecNode]:
        """
        Detect code that doesn't map back to any spec.

        This represents underspecification - code generated by LLM
        that wasn't explicitly specified.
        """
        underspec = []

        # Enumerate all AST paths
        for path, node in enumerate_ast_paths(code_ast):
            # Skip if mapped
            if path in reverse.ast_to_ir:
                continue

            # This node is unmapped - potential underspecification

            # Find context (nearest mapped parent)
            context_id = None
            parent_path = get_parent_path(path)
            while parent_path:
                if parent_path in reverse.ast_to_ir:
                    context_id = reverse.ast_to_ir[parent_path]
                    break
                parent_path = get_parent_path(parent_path)

            underspec.append(UnderspecNode(
                ast_path=path,
                ast_node=node,
                context_ir_node_id=context_id,
                reason="Generated code without spec correspondence"
            ))

        return underspec

    def update_mapping_after_edit(
        self,
        mapping: BidirectionalMapping,
        node: IRNode,
        new_code: str,
        ir: ProgramIR
    ):
        """
        Incrementally update mapping after an edit.

        This is more efficient than rebuilding entire mapping.
        """
        # Parse new code
        try:
            new_ast = ast.parse(new_code)
        except SyntaxError:
            return

        # Re-classify node
        if not self.classifier:
            self.classifier = NodeClassifier(ir)

        category = self.classifier.classify(node)

        # Re-map this specific node
        ast_by_line = self._build_line_index(new_ast)

        # Remove old mapping
        old_paths = mapping.forward.get_ast_paths(node.id)
        for path in old_paths:
            if path in mapping.reverse.ast_to_ir:
                del mapping.reverse.ast_to_ir[path]

        # Add new mapping based on category
        if category == MappingCategory.DIRECT:
            self._map_direct_node(
                node, new_ast, ast_by_line,
                mapping.forward, mapping.reverse
            )
        elif category == MappingCategory.HYBRID:
            self._map_hybrid_node(
                node, new_ast, ast_by_line,
                mapping.forward, mapping.reverse, ir
            )
        elif category == MappingCategory.NL:
            self._map_nl_node(
                node, new_ast, ast_by_line,
                mapping.forward, mapping.reverse
            )


def extract_subtree_for_node(
    node: IRNode,
    code_ast: ast.Module,
    mapping: BidirectionalMapping
) -> List[ast.stmt]:
    """
    Extract all AST statements that belong to this IR node.

    For NL nodes, this may be multiple statements.
    For DIRECT/HYBRID, typically single or pair of statements.
    """
    category = mapping.get_category(node.id)

    if category == MappingCategory.NL:
        nl_map = mapping.forward.nl_mappings.get(node.id)
        if nl_map:
            return nl_map.subtree_ast_nodes
        return []

    elif category == MappingCategory.HYBRID:
        hybrid_map = mapping.forward.hybrid_mappings.get(node.id)
        if hybrid_map:
            return hybrid_map.usage_ast_nodes + hybrid_map.definition_ast_nodes
        return []

    else:  # DIRECT
        paths = mapping.forward.get_ast_paths(node.id)
        # Would need to resolve paths to actual nodes
        # For now, return empty
        return []
