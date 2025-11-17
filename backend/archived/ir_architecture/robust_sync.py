"""
Robust synchronization using enhanced mapping system.

This module integrates the robust mapper with the existing IR sync system
to provide improved bidirectional synchronization.
"""

from typing import List, Tuple, Optional, Set
from backend.ir import ProgramIR, IRNode, NodeStatus
from backend.ir_sync import IRSync, SyncResult
from backend.ast_parser import parse_semiformal
from backend.skeleton_generator import generate_skeleton
from backend.mapping_types import (
    BidirectionalMapping, MappingCategory, EditInfo, EditType
)
from backend.robust_mapper import RobustMapper
from backend.node_classifier import NodeClassifier, classify_edit_type
from backend.edit_dispatcher import EditActionDispatcher, determine_edit_actions, RegenerationSlicer
from backend.diff_generator import DiffGenerator


class RobustIRSync:
    """
    Enhanced IR synchronization with robust mapping.

    This extends IRSync with:
    - Fine-grained node classification (DIRECT, HYBRID, NL)
    - Smart edit dispatching (direct transform vs LLM generation)
    - Underspecification tracking
    - Minimal regeneration slicing
    """

    def __init__(self, use_llm: bool = True):
        self.ir: Optional[ProgramIR] = None
        self.mapping: Optional[BidirectionalMapping] = None
        self.mapper = RobustMapper()
        self.classifier: Optional[NodeClassifier] = None
        self.use_llm = use_llm
        self.generator = None

        # Only initialize generator if LLM is needed
        if use_llm:
            try:
                self.generator = DiffGenerator()
            except Exception:
                # API key not available - LLM won't work
                self.use_llm = False

        # For backward compatibility
        self.legacy_sync = IRSync()

    def set_ir(self, ir: ProgramIR):
        """Set the IR and initialize classifier."""
        self.ir = ir
        self.legacy_sync.ir = ir
        self.classifier = NodeClassifier(ir)

    def merge_and_transform_robust(
        self,
        new_spec: str,
        current_code: Optional[str] = None
    ) -> Tuple[ProgramIR, Optional[BidirectionalMapping]]:
        """
        Merge new spec with existing IR using robust mapping.

        This is the enhanced version of merge_and_transform that:
        1. Classifies all nodes
        2. Detects edits with categories
        3. Applies direct transformations where possible
        4. Builds/updates bidirectional mapping

        Args:
            new_spec: Updated spec source
            current_code: Current generated code (for mapping)

        Returns:
            (updated_ir, updated_mapping)
        """
        # Parse new spec
        new_ir = parse_semiformal(new_spec)

        # Store old IR
        old_ir = self.ir

        # Detect changes if we have existing IR
        changed_nodes = []
        if old_ir:
            # Classify nodes in both IRs
            old_classifier = NodeClassifier(old_ir)
            new_classifier = NodeClassifier(new_ir)

            # Detect structural changes
            from backend.ast_operations import TreeDiffer
            differ = TreeDiffer()
            structural_changes = differ.diff_specs(old_ir, new_ir)

            # Merge IRs (preserves generated code)
            changes = old_ir.merge_from_spec_update(new_ir)
            self.ir = old_ir

            # Build list of changed nodes with edit info
            for change in structural_changes:
                node = self.ir.nodes.get(change.node_id)
                if not node:
                    continue

                # Classify edit type
                # Find corresponding old node
                old_node = old_ir.nodes.get(change.node_id)
                if old_node:
                    edit_type, metadata = classify_edit_type(old_node, node)

                    edit = EditInfo(
                        edit_type=edit_type,
                        node_id=node.id,
                        old_value=old_node.spec_text,
                        new_value=node.spec_text,
                        metadata=metadata
                    )

                    changed_nodes.append((node, edit))
        else:
            # First time
            self.ir = new_ir

        # Rebuild or update mapping
        if current_code:
            if self.mapping and changed_nodes:
                # Incremental update (more efficient)
                for node, edit in changed_nodes:
                    self.mapper.update_mapping_after_edit(
                        self.mapping, node, current_code, self.ir
                    )
            else:
                # Full rebuild
                self.mapping = self.mapper.build_mapping(self.ir, current_code)
        else:
            # No code yet, will build after skeleton generation
            self.mapping = None

        # Apply edit actions
        if changed_nodes and self.mapping:
            dispatcher = EditActionDispatcher(self.ir, self.mapping)

            for node, edit in changed_nodes:
                dispatcher.dispatch(node, edit)

        return self.ir, self.mapping

    def generate_with_mapping(
        self,
        spec: str,
        use_llm: bool = True
    ) -> Tuple[str, BidirectionalMapping]:
        """
        Generate code with robust mapping.

        Args:
            spec: Spec source
            use_llm: Whether to use LLM for incomplete nodes

        Returns:
            (generated_code, bidirectional_mapping)
        """
        # Merge and transform
        self.merge_and_transform_robust(spec)

        if not self.ir:
            return "", BidirectionalMapping(
                forward=IRToPythonMapping(),
                reverse=PythonToIRMapping()
            )

        # Generate skeleton
        skeleton_code = generate_skeleton(self.ir)

        # Build initial mapping
        self.mapping = self.mapper.build_mapping(self.ir, skeleton_code)

        # Determine what needs LLM generation
        if use_llm:
            incomplete_nodes = self.ir.get_incomplete_nodes()

            if incomplete_nodes:
                # Use regeneration slicer to minimize LLM calls
                slicer = RegenerationSlicer(self.ir, self.mapping)
                nodes_to_regen = slicer.compute_regen_slice(
                    {n.id for n in incomplete_nodes}
                )

                # Generate with LLM
                generated_code, diffs = self.generator.generate_from_ir(self.ir)

                # Rebuild mapping with generated code
                self.mapping = self.mapper.build_mapping(self.ir, generated_code)

                return generated_code, self.mapping

        return skeleton_code, self.mapping

    def sync_spec_change_robust(
        self,
        old_spec: str,
        new_spec: str
    ) -> SyncResult:
        """
        Synchronize spec changes using robust mapping.

        This determines which changes need:
        - Direct transformation (no LLM)
        - LLM regeneration

        Args:
            old_spec: Previous spec
            new_spec: New spec

        Returns:
            SyncResult with code and regeneration info
        """
        # Parse old spec to build baseline IR
        if not self.ir:
            self.ir = parse_semiformal(old_spec)

        # Generate baseline code to establish mapping
        baseline_code = generate_skeleton(self.ir)
        self.mapping = self.mapper.build_mapping(self.ir, baseline_code)

        # Parse new spec
        new_ir = parse_semiformal(new_spec)

        # Detect changes
        from backend.ast_operations import TreeDiffer
        differ = TreeDiffer()
        structural_changes = differ.diff_specs(self.ir, new_ir)

        # Merge
        changes = self.ir.merge_from_spec_update(new_ir)

        # Classify edits and determine actions
        changed_nodes = []
        for change in structural_changes:
            node = self.ir.nodes.get(change.node_id)
            if not node:
                continue

            # Find old node for comparison
            old_node = None
            for old_n in self.ir.nodes.values():
                if old_n.id == change.node_id:
                    old_node = old_n
                    break

            if old_node:
                edit_type, metadata = classify_edit_type(old_node, node)
                edit = EditInfo(
                    edit_type=edit_type,
                    node_id=node.id,
                    old_value=old_node.spec_text,
                    new_value=node.spec_text,
                    metadata=metadata
                )
                changed_nodes.append((node, edit))

        # Determine actions
        direct_nodes, llm_nodes = determine_edit_actions(
            self.ir, self.mapping, changed_nodes
        )

        # Apply direct transformations
        for node in direct_nodes:
            # Already applied by dispatcher
            pass

        # Generate skeleton with transformations
        skeleton_code = generate_skeleton(self.ir)

        # Update mapping
        self.mapping = self.mapper.build_mapping(self.ir, skeleton_code)

        # Generate with LLM if needed
        if llm_nodes:
            generated_code, diffs = self.generator.generate_from_ir(self.ir)
            final_code = generated_code
            needs_regen = True
        else:
            final_code = skeleton_code
            diffs = []
            needs_regen = False

        affected_ids = [n.id for n in (direct_nodes + llm_nodes)]

        return SyncResult(
            updated_source=final_code,
            diffs=diffs,
            affected_nodes=affected_ids,
            needs_regeneration=needs_regen,
            message=f"Robust sync: {len(direct_nodes)} direct, {len(llm_nodes)} LLM",
            ir=self.ir
        )

    def get_mapping_info(self) -> dict:
        """
        Get information about the current mapping.

        Useful for debugging and UI visualization.
        """
        if not self.mapping or not self.ir:
            return {}

        info = {
            'total_nodes': len(self.ir.nodes),
            'categories': {
                'direct': 0,
                'hybrid': 0,
                'nl': 0
            },
            'underspecified': len(self.mapping.underspec_nodes),
            'nodes': []
        }

        for node_id, node in self.ir.nodes.items():
            category = self.mapping.get_category(node_id)
            if category:
                info['categories'][category.value] += 1

            node_info = {
                'id': node_id,
                'name': node.name,
                'type': node.node_type.value,
                'category': category.value if category else 'unknown',
                'status': node.status.value,
                'ast_paths': self.mapping.forward.get_ast_paths(node_id),
                'requires_regeneration': getattr(node, 'requires_regeneration', False)
            }

            info['nodes'].append(node_info)

        return info


def create_robust_sync() -> RobustIRSync:
    """
    Factory function to create robust sync instance.
    """
    return RobustIRSync()
