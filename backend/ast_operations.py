"""
AST-level operations for bidirectional programming.

This module provides:
1. Tree diff algorithm for detecting changes
2. AST-level mapping between spec and code
3. Structural transformations (signature changes, LHS updates, etc.)
4. Backward slicing from code AST to spec AST
"""

import ast
from typing import Dict, List, Tuple, Optional, Set, Any
from dataclasses import dataclass
from enum import Enum

from ir import IRNode, NodeType, ProgramIR


class ChangeType(Enum):
    """Types of changes detected in tree diff."""
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    MOVED = "moved"
    SIGNATURE_CHANGED = "signature_changed"
    LHS_CHANGED = "lhs_changed"
    RHS_CHANGED = "rhs_changed"


@dataclass
class ASTChange:
    """Represents a change detected in tree diff."""
    change_type: ChangeType
    node_id: str  # IR node ID
    old_ast: Optional[ast.AST]
    new_ast: Optional[ast.AST]
    old_text: str
    new_text: str
    metadata: Dict[str, Any]


class ASTMapper:
    """
    Maintains bidirectional mapping between spec AST and code AST.
    
    This is the key to systematic bidirectional programming:
    - Each spec node maps to one or more code nodes
    - Each code node maps back to spec node(s)
    - Enables structural transformations without regeneration
    """
    
    def __init__(self):
        self.spec_to_code: Dict[str, List[str]] = {}  # spec_node_id -> [code_ast_paths]
        self.code_to_spec: Dict[str, str] = {}  # code_ast_path -> spec_node_id
    
    def add_mapping(self, spec_node_id: str, code_ast_path: str):
        """Add bidirectional mapping between spec node and code AST node."""
        if spec_node_id not in self.spec_to_code:
            self.spec_to_code[spec_node_id] = []
        self.spec_to_code[spec_node_id].append(code_ast_path)
        self.code_to_spec[code_ast_path] = spec_node_id
    
    def get_code_paths(self, spec_node_id: str) -> List[str]:
        """Get all code AST paths for a spec node."""
        return self.spec_to_code.get(spec_node_id, [])
    
    def get_spec_node(self, code_ast_path: str) -> Optional[str]:
        """Get spec node ID for a code AST path."""
        return self.code_to_spec.get(code_ast_path)
    
    def update_mapping(self, old_spec_node_id: str, new_spec_node_id: str):
        """Update mapping when spec node ID changes."""
        if old_spec_node_id in self.spec_to_code:
            paths = self.spec_to_code[old_spec_node_id]
            self.spec_to_code[new_spec_node_id] = paths
            del self.spec_to_code[old_spec_node_id]
            
            for path in paths:
                self.code_to_spec[path] = new_spec_node_id


class TreeDiffer:
    """
    Computes structural differences between two ASTs.
    
    Uses tree diff algorithm to identify:
    - Added/removed/modified nodes
    - Signature changes
    - LHS/RHS changes in assignments
    """
    
    def diff_specs(self, old_ir: ProgramIR, new_ir: ProgramIR) -> List[ASTChange]:
        """
        Compute differences between old and new spec IRs.
        
        This is more sophisticated than simple node comparison:
        - Uses AST structure and line numbers to match nodes
        - Identifies structural vs semantic changes
        - Enables targeted transformations
        
        Args:
            old_ir: Previous IR state
            new_ir: New IR state after spec edit
        
        Returns:
            List of detected changes
        """
        changes = []
        
        # Match nodes by line number AND type (not name, since name can change)
        old_nodes_by_line = {}
        for n in old_ir.nodes.values():
            if n.spec_location:
                key = (n.spec_location.line, n.node_type)
                old_nodes_by_line[key] = n
        
        new_nodes_by_line = {}
        for n in new_ir.nodes.values():
            if n.spec_location:
                key = (n.spec_location.line, n.node_type)
                new_nodes_by_line[key] = n
        
        # Also keep track by name for detecting moved nodes
        old_nodes_by_key = {(n.node_type, n.name): n for n in old_ir.nodes.values()}
        new_nodes_by_key = {(n.node_type, n.name): n for n in new_ir.nodes.values()}
        
        # First, match by line number (nodes on same line are likely related)
        processed_old = set()
        processed_new = set()
        
        for line_key in set(old_nodes_by_line.keys()) & set(new_nodes_by_line.keys()):
            old_node = old_nodes_by_line[line_key]
            new_node = new_nodes_by_line[line_key]
            
            processed_old.add(old_node.id)
            processed_new.add(new_node.id)
            
            # Detect specific change types
            change = self._detect_change_type(old_node, new_node)
            if change:
                changes.append(change)
        
        # Find removed nodes (not matched by line)
        for key, old_node in old_nodes_by_key.items():
            if old_node.id not in processed_old:
                changes.append(ASTChange(
                    change_type=ChangeType.REMOVED,
                    node_id=old_node.id,
                    old_ast=old_node.spec_ast,
                    new_ast=None,
                    old_text=old_node.spec_text,
                    new_text="",
                    metadata={}
                ))
        
        # Find added nodes (not matched by line)
        for key, new_node in new_nodes_by_key.items():
            if new_node.id not in processed_new:
                changes.append(ASTChange(
                    change_type=ChangeType.ADDED,
                    node_id=new_node.id,
                    old_ast=None,
                    new_ast=new_node.spec_ast,
                    old_text="",
                    new_text=new_node.spec_text,
                    metadata={}
                ))
        
        return changes
    
    def _detect_change_type(self, old_node: IRNode, new_node: IRNode) -> Optional[ASTChange]:
        """
        Detect specific type of change between old and new node.
        
        This is where we distinguish structural from semantic changes.
        """
        # If text hasn't changed, no change
        if old_node.spec_text == new_node.spec_text:
            return None
        
        # For variable assignments, check if LHS changed
        if old_node.node_type == NodeType.VARIABLE_ASSIGN or old_node.node_type == NodeType.NL_EXPRESSION:
            old_lhs = self._extract_lhs(old_node)
            new_lhs = self._extract_lhs(new_node)
            
            if old_lhs != new_lhs:
                # LHS changed (e.g., x -> x,y)
                return ASTChange(
                    change_type=ChangeType.LHS_CHANGED,
                    node_id=old_node.id,
                    old_ast=old_node.spec_ast,
                    new_ast=new_node.spec_ast,
                    old_text=old_node.spec_text,
                    new_text=new_node.spec_text,
                    metadata={
                        'old_lhs': old_lhs,
                        'new_lhs': new_lhs
                    }
                )
            
            # RHS changed
            old_rhs = self._extract_rhs(old_node)
            new_rhs = self._extract_rhs(new_node)
            
            if old_rhs != new_rhs:
                return ASTChange(
                    change_type=ChangeType.RHS_CHANGED,
                    node_id=old_node.id,
                    old_ast=old_node.spec_ast,
                    new_ast=new_node.spec_ast,
                    old_text=old_node.spec_text,
                    new_text=new_node.spec_text,
                    metadata={
                        'old_rhs': old_rhs,
                        'new_rhs': new_rhs
                    }
                )
        
        # For function definitions, check if signature changed
        elif old_node.node_type == NodeType.FUNCTION_DEF:
            if old_node.spec_signature != new_node.spec_signature:
                return ASTChange(
                    change_type=ChangeType.SIGNATURE_CHANGED,
                    node_id=old_node.id,
                    old_ast=old_node.spec_ast,
                    new_ast=new_node.spec_ast,
                    old_text=old_node.spec_text,
                    new_text=new_node.spec_text,
                    metadata={
                        'old_signature': old_node.spec_signature,
                        'new_signature': new_node.spec_signature
                    }
                )
        
        # Generic modification
        return ASTChange(
            change_type=ChangeType.MODIFIED,
            node_id=old_node.id,
            old_ast=old_node.spec_ast,
            new_ast=new_node.spec_ast,
            old_text=old_node.spec_text,
            new_text=new_node.spec_text,
            metadata={}
        )
    
    def _extract_lhs(self, node: IRNode) -> List[str]:
        """Extract LHS variable names from assignment node."""
        # First check metadata (from line-by-line parser)
        if 'lhs' in node.metadata:
            return node.metadata['lhs']
        
        if not node.spec_ast:
            # Fallback to text parsing
            if '=' in node.spec_text:
                lhs = node.spec_text.split('=')[0].strip()
                return [v.strip() for v in lhs.split(',')]
            return [node.name]
        
        if isinstance(node.spec_ast, ast.Assign):
            targets = node.spec_ast.targets[0]
            if isinstance(targets, ast.Name):
                return [targets.id]
            elif isinstance(targets, ast.Tuple):
                return [elt.id for elt in targets.elts if isinstance(elt, ast.Name)]
        
        return [node.name]
    
    def _extract_rhs(self, node: IRNode) -> str:
        """Extract RHS expression from assignment node."""
        if '=' in node.spec_text:
            return node.spec_text.split('=', 1)[1].strip()
        return ""


class StructuralTransformer:
    """
    Applies structural transformations to code AST without LLM.
    
    Handles:
    - LHS changes (x -> x,y)
    - Signature changes (func(a) -> func(a, b))
    - Argument reordering
    """
    
    def __init__(self, mapper: ASTMapper):
        self.mapper = mapper
    
    def apply_change(self, change: ASTChange, code_ast: ast.Module, ir: ProgramIR) -> ast.Module:
        """
        Apply a structural change to the code AST.
        
        Args:
            change: The change to apply
            code_ast: The code AST to transform
            ir: Program IR for context
        
        Returns:
            Transformed code AST
        """
        if change.change_type == ChangeType.LHS_CHANGED:
            return self._apply_lhs_change(change, code_ast, ir)
        elif change.change_type == ChangeType.SIGNATURE_CHANGED:
            return self._apply_signature_change(change, code_ast, ir)
        elif change.change_type == ChangeType.RHS_CHANGED:
            # RHS changes typically require LLM regeneration
            # But we can preserve structure and mark for regen
            pass
        
        return code_ast
    
    def _apply_lhs_change(self, change: ASTChange, code_ast: ast.Module, ir: ProgramIR) -> ast.Module:
        """
        Apply LHS change (e.g., x -> x,y).
        
        Strategy:
        1. Find the assignment in code AST
        2. Update the target to match new LHS
        3. If RHS is tuple/list, adjust accordingly
        """
        # Get the IR node
        node = ir.nodes.get(change.node_id)
        if not node:
            return code_ast
        
        # Get old and new LHS
        old_lhs = change.metadata.get('old_lhs', [])
        new_lhs = change.metadata.get('new_lhs', [])
        
        # If no code_ast_path, we need to find the assignment manually
        # This happens when code is generated but not yet parsed into AST
        assignment = None
        assignment_index = None
        
        for i, stmt in enumerate(code_ast.body):
            if isinstance(stmt, ast.Assign):
                # Check if this is the right assignment by looking at LHS
                if stmt.targets and isinstance(stmt.targets[0], (ast.Name, ast.Tuple)):
                    current_lhs = []
                    if isinstance(stmt.targets[0], ast.Name):
                        current_lhs = [stmt.targets[0].id]
                    elif isinstance(stmt.targets[0], ast.Tuple):
                        current_lhs = [elt.id for elt in stmt.targets[0].elts if isinstance(elt, ast.Name)]
                    
                    if current_lhs == old_lhs:
                        assignment = stmt
                        assignment_index = i
                        break
        
        if not assignment:
            return code_ast
        
        # Create new target
        if len(new_lhs) == 1:
            # Single variable
            new_target = ast.Name(id=new_lhs[0], ctx=ast.Store())
        else:
            # Multiple variables (tuple unpacking)
            new_target = ast.Tuple(
                elts=[ast.Name(id=name, ctx=ast.Store()) for name in new_lhs],
                ctx=ast.Store()
            )
        
        # Update the assignment
        assignment.targets = [new_target]
        
        # Fix AST locations
        ast.fix_missing_locations(code_ast)
        
        return code_ast
    
    def _apply_signature_change(self, change: ASTChange, code_ast: ast.Module, ir: ProgramIR) -> ast.Module:
        """
        Apply signature change to function definition.
        
        Strategy:
        1. Find function definition in code AST
        2. Update arguments to match new signature
        3. Preserve function body
        """
        # Get the IR node
        node = ir.nodes.get(change.node_id)
        if not node or not node.code_ast_path:
            return code_ast
        
        # Find the function node in code AST
        func_def = self._get_node_by_path(code_ast, node.code_ast_path)
        if not func_def or not isinstance(func_def, ast.FunctionDef):
            return code_ast
        
        # Parse new signature from spec
        if node.spec_ast and isinstance(node.spec_ast, ast.FunctionDef):
            # Update arguments from new spec
            func_def.args = node.spec_ast.args
            func_def.returns = node.spec_ast.returns
            
            # Fix AST locations
            ast.fix_missing_locations(code_ast)
        
        return code_ast
    
    def _get_node_by_path(self, tree: ast.AST, path: str) -> Optional[ast.AST]:
        """Get AST node by path (e.g., 'body[0].body[1]')."""
        if not path:
            return None
        
        node = tree
        for part in path.split('.'):
            if '[' in part:
                # Array access like body[0]
                attr, index = part.split('[')
                index = int(index.rstrip(']'))
                node = getattr(node, attr)[index]
            else:
                # Attribute access like body
                node = getattr(node, part)
        
        return node


def generate_ast_path(tree: ast.AST, target: ast.AST, path: str = "") -> Optional[str]:
    """
    Generate path to target node in tree.
    
    Returns path like "body[0].body[1]" that can be used to navigate to target.
    """
    if tree is target:
        return path
    
    for field, value in ast.iter_fields(tree):
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    new_path = f"{path}.{field}[{i}]" if path else f"{field}[{i}]"
                    result = generate_ast_path(item, target, new_path)
                    if result:
                        return result
        elif isinstance(value, ast.AST):
            new_path = f"{path}.{field}" if path else field
            result = generate_ast_path(value, target, new_path)
            if result:
                return result
    
    return None

