"""
Edit action dispatcher for robust bidirectional synchronization.

Determines and executes appropriate actions based on node category and edit type.
"""

import ast
from typing import List, Set, Optional, Tuple
from ir import IRNode, ProgramIR, NodeStatus
from mapping_types import (
    MappingCategory, EditType, EditInfo, BidirectionalMapping
)
from ast_operations import StructuralTransformer, ASTChange, ChangeType


class EditActionDispatcher:
    """
    Dispatches edit actions based on (node category, edit type) matrix.

    This implements the action dispatch table from ROBUST_MAPPING_DESIGN.md.
    """

    def __init__(self, ir: ProgramIR, mapping: BidirectionalMapping):
        self.ir = ir
        self.mapping = mapping
        self.transformer = StructuralTransformer()

    def dispatch(self, node: IRNode, edit: EditInfo) -> bool:
        """
        Execute appropriate action for this edit.

        Args:
            node: The IR node being edited
            edit: Information about the edit

        Returns:
            True if LLM regeneration is required, False otherwise
        """
        category = self.mapping.get_category(node.id)
        if not category:
            # Unknown node - treat as NL
            category = MappingCategory.NL

        edit_type = edit.edit_type

        # Dispatch based on (category, edit_type)
        if category == MappingCategory.DIRECT:
            return self._handle_direct_edit(node, edit)

        elif category == MappingCategory.HYBRID:
            return self._handle_hybrid_edit(node, edit)

        elif category == MappingCategory.NL:
            return self._handle_nl_edit(node, edit)

        return True  # Default: require regeneration

    def _handle_direct_edit(self, node: IRNode, edit: EditInfo) -> bool:
        """
        Handle edit to DIRECT node.

        Most edits can be handled without LLM.
        """
        if edit.edit_type == EditType.STRUCTURAL:
            # Apply AST transformation
            success = self._apply_structural_transform(node, edit)
            if success:
                node.requires_regeneration = False
                return False  # No LLM needed
            else:
                # Transformation failed, need regeneration
                node.requires_regeneration = True
                return True

        elif edit.edit_type == EditType.VALUE:
            # Direct text replacement
            self._apply_value_change(node, edit)
            node.requires_regeneration = False
            return False  # No LLM needed

        elif edit.edit_type == EditType.SIGNATURE:
            # Update signature in AST
            success = self._apply_signature_change(node, edit)

            if success:
                # Check dependents
                needs_regen = self._mark_dependents_for_regen(node)
                node.requires_regeneration = False
                return needs_regen
            else:
                node.requires_regeneration = True
                return True

        elif edit.edit_type == EditType.ADDITION:
            # New node - will be handled by skeleton generator
            node.requires_regeneration = False
            return False

        elif edit.edit_type == EditType.REMOVAL:
            # Node removed - cleanup in mapping
            self._remove_node_mapping(node)
            return False

        elif edit.edit_type == EditType.SEMANTIC:
            # Content changed - might need reclassification
            node.requires_regeneration = True
            return True

        return True  # Default: need regeneration

    def _handle_hybrid_edit(self, node: IRNode, edit: EditInfo) -> bool:
        """
        Handle edit to HYBRID node.

        Usage edits are direct, definition edits need LLM.
        """
        if edit.edit_type == EditType.STRUCTURAL:
            # Determine if affects usage or definition
            if edit.affects_usage:
                # Transform call site directly
                success = self._apply_structural_transform(node, edit)
                if not success:
                    node.requires_regeneration = True
                    return True

            if edit.affects_definition:
                # Mark definition for regeneration
                node.requires_regeneration = True
                node.status = NodeStatus.NEEDS_REGEN
                return True

            # Only usage affected and transformed successfully
            return False

        elif edit.edit_type == EditType.SIGNATURE:
            # Update signature (direct)
            self._apply_signature_change(node, edit)

            # Mark definition for regeneration
            node.requires_regeneration = True
            node.status = NodeStatus.NEEDS_REGEN
            return True

        elif edit.edit_type == EditType.SEMANTIC:
            # Content change - regenerate definition
            node.requires_regeneration = True
            node.status = NodeStatus.NEEDS_REGEN
            return True

        return True  # Default: need regeneration

    def _handle_nl_edit(self, node: IRNode, edit: EditInfo) -> bool:
        """
        Handle edit to NL node.

        Any edit requires regeneration of entire subtree.
        """
        # Mark for regeneration
        node.requires_regeneration = True
        node.status = NodeStatus.NEEDS_REGEN

        # Mark all AST nodes in subtree
        self._mark_subtree_for_regen(node)

        return True  # Always need LLM for NL changes

    def _apply_structural_transform(self, node: IRNode, edit: EditInfo) -> bool:
        """
        Apply AST transformation for structural change.

        Returns:
            True if successful, False if transformation failed
        """
        # Get current code
        if not node.code_text:
            return False

        try:
            # Parse current code
            code_ast = ast.parse(node.code_text)

            # Create ASTChange for transformer
            change_metadata = edit.metadata.copy()

            if 'old_lhs' in edit.metadata and 'new_lhs' in edit.metadata:
                # LHS change
                change = ASTChange(
                    change_type=ChangeType.LHS_CHANGED,
                    node_id=node.id,
                    old_ast=code_ast.body[0] if code_ast.body else None,
                    new_ast=None,
                    old_text=node.code_text,
                    new_text="",
                    metadata={
                        'old_lhs': edit.metadata['old_lhs'],
                        'new_lhs': edit.metadata['new_lhs']
                    }
                )

                # Apply transformation
                transformed = self.transformer.apply_change(change, node)

                if transformed:
                    node.code_text = transformed
                    return True

            elif 'old_rhs' in edit.metadata and 'new_rhs' in edit.metadata:
                # RHS change - might be structural
                # For now, just update text
                node.code_text = node.code_text.replace(
                    edit.metadata['old_rhs'],
                    edit.metadata['new_rhs']
                )
                return True

        except Exception as e:
            print(f"Structural transformation failed: {e}")
            return False

        return False

    def _apply_value_change(self, node: IRNode, edit: EditInfo):
        """
        Apply simple value change (direct text replacement).
        """
        old_value = str(edit.old_value)
        new_value = str(edit.new_value)

        if old_value in node.code_text:
            node.code_text = node.code_text.replace(old_value, new_value)

    def _apply_signature_change(self, node: IRNode, edit: EditInfo) -> bool:
        """
        Apply signature change to node.

        Returns:
            True if successful, False otherwise
        """
        # Update node signature
        node.spec_signature = edit.metadata.get('new_signature', node.spec_signature)
        node.code_signature = node.spec_signature

        # If function definition, update AST
        if node.code_ast and isinstance(node.code_ast, ast.FunctionDef):
            # Would need to update function args here
            # For now, mark for regeneration
            return False

        return True

    def _mark_dependents_for_regen(self, node: IRNode) -> bool:
        """
        Mark nodes that depend on this node for regeneration.

        Returns:
            True if any dependent needs regeneration
        """
        needs_regen = False

        for dep_id in node.used_by:
            dep_node = self.ir.nodes.get(dep_id)
            if not dep_node:
                continue

            # Only mark if dependent is HYBRID or NL
            dep_category = self.mapping.get_category(dep_id)
            if dep_category in (MappingCategory.HYBRID, MappingCategory.NL):
                dep_node.requires_regeneration = True
                dep_node.status = NodeStatus.NEEDS_REGEN
                needs_regen = True

        return needs_regen

    def _mark_subtree_for_regen(self, node: IRNode):
        """
        Mark entire subtree for regeneration (for NL nodes).
        """
        # Get all AST paths for this node
        ast_paths = self.mapping.forward.get_ast_paths(node.id)

        # Mark all as needing regeneration
        # (This info can be used by generator to regenerate entire subtree)
        node.metadata['subtree_needs_regen'] = True

    def _remove_node_mapping(self, node: IRNode):
        """
        Remove node from mapping (when node is deleted).
        """
        # Get AST paths
        ast_paths = self.mapping.forward.get_ast_paths(node.id)

        # Remove from reverse mapping
        for path in ast_paths:
            if path in self.mapping.reverse.ast_to_ir:
                del self.mapping.reverse.ast_to_ir[path]

        # Remove from forward mapping
        if node.id in self.mapping.forward.ir_to_ast:
            del self.mapping.forward.ir_to_ast[node.id]


class RegenerationSlicer:
    """
    Computes minimal set of nodes requiring LLM regeneration.

    Uses dependency graph to determine transitive closure of affected nodes.
    """

    def __init__(self, ir: ProgramIR, mapping: BidirectionalMapping):
        self.ir = ir
        self.mapping = mapping

    def compute_regen_slice(self, changed_nodes: Set[str]) -> List[IRNode]:
        """
        Compute minimal slice of nodes requiring regeneration.

        Args:
            changed_nodes: Set of node IDs that were edited

        Returns:
            List of nodes needing regeneration, in topological order
        """
        needs_regen = set()

        # Start with nodes explicitly marked for regeneration
        for node_id in changed_nodes:
            node = self.ir.nodes.get(node_id)
            if node and node.requires_regeneration:
                needs_regen.add(node_id)

        # Propagate through dependencies
        changed = True
        while changed:
            changed = False
            for node_id in list(needs_regen):
                node = self.ir.nodes.get(node_id)
                if not node:
                    continue

                # Add dependents if they rely on this node
                for dep_id in node.used_by:
                    if dep_id in needs_regen:
                        continue

                    dep_node = self.ir.nodes.get(dep_id)
                    if not dep_node:
                        continue

                    # Only add if dependent is HYBRID or NL
                    dep_category = self.mapping.get_category(dep_id)
                    if dep_category != MappingCategory.DIRECT:
                        # Check if dependent uses this node's signature
                        if self._depends_on_signature(dep_node, node):
                            needs_regen.add(dep_id)
                            dep_node.requires_regeneration = True
                            changed = True

        # Return in topological order
        return self._topological_sort([self.ir.nodes[nid] for nid in needs_regen])

    def _depends_on_signature(self, dependent: IRNode, dependency: IRNode) -> bool:
        """
        Check if dependent node relies on dependency's signature.

        This is true for:
        - Function calls depending on function definitions
        - Variable uses depending on variable assignments
        """
        # Check if dependency is in dependent's depends_on set
        if dependency.id in dependent.depends_on:
            # Check if it's a function call dependency
            if dependency.node_type.value == 'function_def':
                return True

        return False

    def _topological_sort(self, nodes: List[IRNode]) -> List[IRNode]:
        """
        Sort nodes in topological order (dependencies first).
        """
        # Build adjacency list
        graph = {node.id: list(node.depends_on) for node in nodes}
        node_map = {node.id: node for node in nodes}

        # Kahn's algorithm
        in_degree = {node_id: 0 for node_id in graph}
        for node_id, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[node_id] += 1

        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_map[node_id])

            # Decrease in-degree for dependents
            for other_id, deps in graph.items():
                if node_id in deps and other_id in in_degree:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        return result


def determine_edit_actions(
    ir: ProgramIR,
    mapping: BidirectionalMapping,
    changed_nodes: List[Tuple[IRNode, EditInfo]]
) -> Tuple[List[IRNode], List[IRNode]]:
    """
    Determine which nodes need direct transformation vs LLM regeneration.

    Args:
        ir: Program IR
        mapping: Bidirectional mapping
        changed_nodes: List of (node, edit_info) tuples

    Returns:
        (nodes_for_direct_transform, nodes_for_llm_regen)
    """
    dispatcher = EditActionDispatcher(ir, mapping)

    direct_transform = []
    llm_regen = []

    # Process each edit
    for node, edit in changed_nodes:
        needs_llm = dispatcher.dispatch(node, edit)

        if needs_llm:
            llm_regen.append(node)
        else:
            direct_transform.append(node)

    # Compute regeneration slice
    if llm_regen:
        slicer = RegenerationSlicer(ir, mapping)
        changed_ids = {node.id for node in llm_regen}
        llm_regen = slicer.compute_regen_slice(changed_ids)

    return direct_transform, llm_regen
