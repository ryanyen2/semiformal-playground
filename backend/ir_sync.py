"""
IR-based bidirectional synchronization using lens mechanisms.

This module implements robust synchronization using the shared IR
and get/put transformations instead of ad-hoc rule-based approaches.
"""

import ast
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from ir import ProgramIR, IRNode, NodeType, NodeStatus, create_node_id
from ast_parser import parse_semiformal
from diff_generator import DiffGenerator, UnifiedDiff
from ast_operations import TreeDiffer, StructuralTransformer, ASTMapper, ChangeType


class SyncDirection(Enum):
    """Direction of synchronization."""
    SPEC_TO_CODE = "spec_to_code"  # Get transformation
    CODE_TO_SPEC = "code_to_spec"  # Put transformation


@dataclass
class SyncResult:
    """Result of a synchronization operation."""
    updated_source: str
    diffs: List[UnifiedDiff]
    affected_nodes: List[str]  # IDs of affected nodes
    needs_regeneration: bool
    message: str
    ir: Optional[ProgramIR] = None  # Updated IR


class IRSync:
    """
    Manages bidirectional synchronization using IR and lenses.
    
    This replaces the rule-based sync with a principled approach
    based on the lens laws.
    """
    
    def __init__(self, use_llm: bool = True):
        self.ir: Optional[ProgramIR] = None
        self.generator = DiffGenerator() if use_llm else None
        self.mapper = ASTMapper()
        self.differ = TreeDiffer()
        self.transformer = StructuralTransformer(self.mapper)
    
    def merge_and_transform(
        self,
        new_spec: str
    ) -> None:
        """
        Merge new spec with existing IR and apply structural transformations.
        
        This is the fast path that doesn't call LLM - used by /skeleton.
        
        Args:
            new_spec: Updated spec source
        """
        # Parse new spec to build new IR
        new_ir = parse_semiformal(new_spec)
        
        # Store old IR for comparison
        old_ir = self.ir
        
        # If we have an existing IR, detect structural changes
        structural_changes = []
        if old_ir:
            # Use tree diff to detect specific changes
            structural_changes = self.differ.diff_specs(old_ir, new_ir)
            
            # Merge the changes
            changes = old_ir.merge_from_spec_update(new_ir)
            self.ir = old_ir  # Keep the merged IR
        else:
            # First time - just use the new IR
            self.ir = new_ir
            changes = {}
        
        # Apply structural transformations
        # This handles LHS changes, signature changes, etc. without LLM
        if structural_changes:
            self._apply_structural_transformations(structural_changes)
    
    def sync_spec_change(
        self,
        old_spec: str,
        new_spec: str
    ) -> SyncResult:
        """
        Synchronize spec changes to code (GET transformation).
        
        NEW APPROACH:
        1. Detect changes using tree diff algorithm
        2. Apply structural transformations (no LLM)
        3. Generate code with LLM for semantic changes
        
        Args:
            old_spec: Previous spec source
            new_spec: Updated spec source
        
        Returns:
            SyncResult with generated code and diffs
        """
        # First, do merge and structural transformations
        self.merge_and_transform(new_spec)

        # Then apply LLM generation for incomplete nodes (if generator available)
        if self.generator:
            generated_code, diffs = self.generator.generate_from_ir(self.ir)
        else:
            # No LLM available - just return skeleton
            from skeleton_generator import generate_skeleton
            generated_code = generate_skeleton(self.ir)
            diffs = []

        affected_node_ids = [node.id for node in self.ir.get_incomplete_nodes()]

        return SyncResult(
            updated_source=generated_code,
            diffs=diffs,
            affected_nodes=affected_node_ids,
            needs_regeneration=len(affected_node_ids) > 0,
            message=f"Synced spec changes, {len(affected_node_ids)} incomplete",
            ir=self.ir
        )
    
    def _apply_structural_transformations(self, changes: List) -> None:
        """
        Apply structural transformations to preserve generated code.
        
        Args:
            changes: List of ASTChange objects
        """
        import ast
        
        for change in changes:
            # Only apply to structural changes
            if change.change_type in (ChangeType.LHS_CHANGED, ChangeType.SIGNATURE_CHANGED):
                node = self.ir.nodes.get(change.node_id)
                if not node or not node.code_text:
                    continue
                
                # Parse the existing code
                try:
                    code_ast = ast.parse(node.code_text)
                    
                    # Apply transformation
                    transformed_ast = self.transformer.apply_change(change, code_ast, self.ir)
                    
                    # Update the node's code
                    node.code_text = ast.unparse(transformed_ast)
                    
                    # Mark as user-edited to preserve it
                    if node.status.value == 'generated':
                        node.status = NodeStatus.USER_EDITED
                except Exception as e:
                    # If transformation fails, mark for regeneration
                    print(f"Warning: Structural transformation failed for {node.name}: {e}")
                    if node.status.value in ('generated', 'user_edited'):
                        node.status = NodeStatus.NEEDS_REGEN
    
    def sync_code_change(
        self,
        spec: str,
        old_code: str,
        new_code: str
    ) -> SyncResult:
        """
        Synchronize code changes back to spec (PUT transformation).

        Strategy:
        1. Parse both old and new code to AST
        2. Detect what changed at AST level
        3. Update IR nodes with new code
        4. Mark nodes as USER_EDITED
        5. Optionally update spec text for synced nodes

        Args:
            spec: Current spec source
            old_code: Previous generated code
            new_code: Updated code

        Returns:
            SyncResult with updated spec
        """
        import ast as ast_module

        # Parse spec to get IR if not already loaded
        if not self.ir:
            self.ir = parse_semiformal(spec)

        # Parse old and new code
        try:
            old_ast = ast_module.parse(old_code)
            new_ast = ast_module.parse(new_code)
        except SyntaxError as e:
            return SyncResult(
                updated_source=spec,
                diffs=[],
                affected_nodes=[],
                needs_regeneration=False,
                message=f"Code syntax error: {e}",
                ir=self.ir
            )

        # Detect code changes at AST level
        code_changes = self._detect_code_changes_ast(old_ast, new_ast)

        # Apply changes to IR
        affected_nodes = []
        updated_spec_lines = spec.split('\n')

        for change_info in code_changes:
            node = self._find_node_by_code(change_info)
            if node:
                # Update node with new code
                node.code_text = change_info['new_text']
                node.status = NodeStatus.USER_EDITED
                affected_nodes.append(node.id)

                # Important: Also update metadata to track LHS for future diffs
                # Extract LHS from new code
                if '=' in change_info['new_text']:
                    lhs_part = change_info['new_text'].split('=')[0].strip()
                    # Parse LHS to get variable names
                    lhs_vars = [v.strip() for v in lhs_part.replace('(', '').replace(')', '').split(',')]
                    node.metadata['lhs'] = lhs_vars

                # For SYNCED nodes, also update spec text
                # For NL/INCOMPLETE nodes, just mark as user-edited
                if change_info['type'] == 'assignment' and node.node_type == NodeType.VARIABLE_ASSIGN:
                    # Update spec to reflect new code (if it was synced)
                    if node.spec_location and node.status == NodeStatus.SYNCED:
                        line_idx = node.spec_location.line - 1
                        if 0 <= line_idx < len(updated_spec_lines):
                            # Keep the variable name, update to show it's now concrete Python
                            updated_spec_lines[line_idx] = change_info['new_text']

        updated_spec = '\n'.join(updated_spec_lines)

        # Generate diffs (simple text diff)
        diffs = []
        if updated_spec != spec:
            import difflib
            diff_lines = list(difflib.unified_diff(
                spec.splitlines(keepends=True),
                updated_spec.splitlines(keepends=True),
                fromfile='spec_before',
                tofile='spec_after'
            ))
            # Simple diff representation
            diffs = [{
                'old_file': 'spec',
                'new_file': 'spec',
                'diff_text': ''.join(diff_lines)
            }]

        return SyncResult(
            updated_source=updated_spec,
            diffs=diffs,
            affected_nodes=affected_nodes,
            needs_regeneration=False,
            message=f"Synced code changes to spec ({len(affected_nodes)} elements)",
            ir=self.ir
        )
    
    def regenerate_node(
        self,
        node_id: str,
        constraint: Optional[str] = None
    ) -> SyncResult:
        """
        Regenerate a specific node with optional new constraint.
        
        Args:
            node_id: ID of node to regenerate
            constraint: Optional new constraint to apply
        
        Returns:
            SyncResult with regenerated code
        """
        if not self.ir:
            return SyncResult(
                updated_source="",
                diffs=[],
                affected_nodes=[],
                needs_regeneration=False,
                message="No IR loaded",
                ir=None
            )
        
        node = self.ir.get_node(node_id)
        if not node:
            return SyncResult(
                updated_source="",
                diffs=[],
                affected_nodes=[],
                needs_regeneration=False,
                message=f"Node {node_id} not found",
                ir=self.ir
            )
        
        # Mark node as incomplete to trigger regeneration
        node.status = NodeStatus.INCOMPLETE
        
        # Add constraint if provided
        if constraint:
            node.metadata['constraint'] = constraint
        
        # Regenerate
        generated_code, diffs = self.generator.generate_from_ir(self.ir)
        
        return SyncResult(
            updated_source=generated_code,
            diffs=diffs,
            affected_nodes=[node_id],
            needs_regeneration=False,
            message=f"Regenerated {node.name}",
            ir=self.ir
        )
    
    def _detect_spec_changes(
        self,
        old_spec: str,
        new_spec: str
    ) -> Dict[str, Any]:
        """
        Detect what changed in spec.
        
        Returns a dictionary of changes with type and location.
        """
        changes = {}
        
        old_lines = old_spec.split('\n')
        new_lines = new_spec.split('\n')
        
        # Simple line-by-line diff
        import difflib
        differ = difflib.Differ()
        diff = list(differ.compare(old_lines, new_lines))
        
        for i, line in enumerate(diff):
            if line.startswith('+'):
                # Added line
                changes[i] = {'type': 'add', 'line': line[2:]}
            elif line.startswith('-'):
                # Removed line
                changes[i] = {'type': 'remove', 'line': line[2:]}
            elif line.startswith('?'):
                # Changed line
                changes[i] = {'type': 'modify', 'line': line[2:]}
        
        return changes
    
    def _detect_code_changes_ast(
        self,
        old_ast: ast.Module,
        new_ast: ast.Module
    ) -> List[Dict[str, Any]]:
        """
        Detect changes between old and new code AST.

        Returns list of change dictionaries with:
        - type: 'assignment', 'function', etc.
        - name: element name
        - old_text: old code
        - new_text: new code
        """
        import ast as ast_module
        changes = []

        # Build mappings of old and new statements
        old_stmts = self._index_ast_statements(old_ast)
        new_stmts = self._index_ast_statements(new_ast)

        # Find changes by comparing statements
        all_names = set(old_stmts.keys()) | set(new_stmts.keys())

        for name in all_names:
            old_stmt = old_stmts.get(name)
            new_stmt = new_stmts.get(name)

            if old_stmt and not new_stmt:
                # Removed
                changes.append({
                    'type': self._get_stmt_type(old_stmt),
                    'name': name,
                    'old_text': ast_module.unparse(old_stmt),
                    'new_text': '',
                    'change': 'removed'
                })
            elif new_stmt and not old_stmt:
                # Added
                changes.append({
                    'type': self._get_stmt_type(new_stmt),
                    'name': name,
                    'old_text': '',
                    'new_text': ast_module.unparse(new_stmt),
                    'change': 'added'
                })
            elif old_stmt and new_stmt:
                # Compare
                old_text = ast_module.unparse(old_stmt)
                new_text = ast_module.unparse(new_stmt)
                if old_text != new_text:
                    changes.append({
                        'type': self._get_stmt_type(new_stmt),
                        'name': name,
                        'old_text': old_text,
                        'new_text': new_text,
                        'change': 'modified'
                    })

        return changes

    def _index_ast_statements(self, tree: ast.Module) -> Dict[str, ast.AST]:
        """Index statements by name for comparison."""
        import ast as ast_module
        index = {}

        for stmt in tree.body:
            if isinstance(stmt, ast_module.FunctionDef):
                index[stmt.name] = stmt
            elif isinstance(stmt, ast_module.Assign):
                # Get target name
                if stmt.targets and isinstance(stmt.targets[0], ast_module.Name):
                    index[stmt.targets[0].id] = stmt
                elif stmt.targets and isinstance(stmt.targets[0], ast_module.Tuple):
                    # Multi-target assignment - use first var
                    if stmt.targets[0].elts and isinstance(stmt.targets[0].elts[0], ast_module.Name):
                        index[stmt.targets[0].elts[0].id] = stmt

        return index

    def _get_stmt_type(self, stmt: ast.AST) -> str:
        """Get statement type as string."""
        import ast as ast_module
        if isinstance(stmt, ast_module.FunctionDef):
            return 'function'
        elif isinstance(stmt, ast_module.Assign):
            return 'assignment'
        elif isinstance(stmt, ast_module.Expr):
            return 'expression'
        return 'unknown'

    def _find_node_by_code(self, change_info: Dict[str, Any]) -> Optional[IRNode]:
        """Find IR node corresponding to code change."""
        if not self.ir:
            return None

        name = change_info['name']
        change_type = change_info['type']

        # Search for node by name and type
        for node in self.ir.nodes.values():
            if node.name == name:
                if change_type == 'function' and node.node_type == NodeType.FUNCTION_DEF:
                    return node
                elif change_type == 'assignment' and node.node_type in (
                    NodeType.VARIABLE_ASSIGN,
                    NodeType.NL_EXPRESSION
                ):
                    return node

        return None

    def _detect_code_changes(
        self,
        old_code: str,
        new_code: str
    ) -> Dict[str, str]:
        """
        Detect changes in code and map to nodes (legacy method).

        Returns a dictionary mapping node IDs to new code text.
        """
        changes = {}

        if not self.ir:
            return changes

        # Parse new code to extract implementations
        new_lines = new_code.split('\n')

        for node_id, node in self.ir.nodes.items():
            if not node.code_location:
                continue

            # Extract node's code from new_code
            start_line = node.code_location.line - 1
            end_line = node.code_location.end_line or start_line

            if start_line < len(new_lines):
                if end_line < len(new_lines):
                    new_text = '\n'.join(new_lines[start_line:end_line + 1])
                else:
                    new_text = new_lines[start_line]

                # Check if changed
                if new_text != node.code_text:
                    changes[node_id] = new_text

        return changes
    
    def get_ir(self) -> Optional[ProgramIR]:
        """Get current IR."""
        return self.ir
    
    def set_ir(self, ir: ProgramIR) -> None:
        """Set IR directly."""
        self.ir = ir


class AutoSync:
    """
    Automatic synchronization manager.
    
    Watches for changes and automatically triggers appropriate sync.
    """
    
    def __init__(self):
        self.sync = IRSync()
        self.last_spec = ""
        self.last_code = ""
    
    def on_spec_change(self, new_spec: str) -> Optional[SyncResult]:
        """
        Called when spec changes (during editing).
        
        Continuously re-parses to update analysis, preserving generated code.
        """
        if new_spec == self.last_spec:
            return None
        
        # Parse new spec
        new_ir = parse_semiformal(new_spec)
        
        # Merge with existing IR if available
        if self.sync.ir:
            changes = self.sync.ir.merge_from_spec_update(new_ir)
        else:
            self.sync.set_ir(new_ir)
            changes = {}
        
        self.last_spec = new_spec
        
        # Return analysis result without generation
        ir = self.sync.get_ir()
        incomplete = ir.get_incomplete_nodes() if ir else []
        
        return SyncResult(
            updated_source="",
            diffs=[],
            affected_nodes=[n.id for n in incomplete],
            needs_regeneration=True,
            message=f"Analyzed spec: {len(incomplete)} incomplete elements",
            ir=ir
        )
    
    def on_spec_save(self, spec: str) -> SyncResult:
        """
        Called when spec is saved (Cmd+S).
        
        Triggers code generation.
        """
        result = self.sync.sync_spec_change(self.last_spec, spec)
        self.last_spec = spec
        self.last_code = result.updated_source
        return result
    
    def on_code_change(self, new_code: str) -> Optional[SyncResult]:
        """
        Called when generated code is edited.
        
        Could auto-sync back to spec or wait for explicit action.
        """
        if new_code == self.last_code:
            return None
        
        # For now, just track changes
        # Could implement auto-sync back to spec here
        self.last_code = new_code
        
        return None
    
    def on_code_save(self, code: str) -> SyncResult:
        """
        Called when code is saved.
        
        Syncs changes back to spec.
        """
        result = self.sync.sync_code_change(
            self.last_spec,
            self.last_code,
            code
        )
        
        self.last_spec = result.updated_source
        self.last_code = code
        
        return result


def create_auto_sync() -> AutoSync:
    """Create an AutoSync instance."""
    return AutoSync()

