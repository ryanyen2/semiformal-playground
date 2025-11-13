"""
Enhanced mapping types and structures for robust bidirectional sync.

This module implements the classification and mapping system described in
ROBUST_MAPPING_DESIGN.md.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Optional, Tuple, Any


class MappingCategory(Enum):
    """
    Classification of IR nodes based on their completeness and mappability.
    """
    DIRECT = "direct"        # Valid Python with all references defined
    HYBRID = "hybrid"        # Python structure with incomplete implementation
    NL = "nl"                # Natural language expression


class EditType(Enum):
    """Types of edits that can be performed on nodes."""
    STRUCTURAL = "structural"    # LHS/RHS shape change (x → x,y)
    SIGNATURE = "signature"      # Function signature change
    VALUE = "value"              # Literal value change
    SEMANTIC = "semantic"        # Natural language content change
    ADDITION = "addition"        # New node added
    REMOVAL = "removal"          # Node removed
    REORDER = "reorder"          # Node moved
    UNKNOWN = "unknown"          # Cannot classify


@dataclass
class HybridMapping:
    """
    Mapping for HYBRID nodes (split between usage and definition).

    Example: `result = process_data(input)` where process_data is undefined
    - usage_ast_paths: ["body[0]"] - the call expression
    - definition_ast_paths: ["body[3]"] - the generated function definition
    """
    usage_ast_paths: List[str] = field(default_factory=list)
    definition_ast_paths: List[str] = field(default_factory=list)
    usage_ast_nodes: List[ast.AST] = field(default_factory=list)
    definition_ast_nodes: List[ast.AST] = field(default_factory=list)


@dataclass
class NLMapping:
    """
    Mapping for NL (natural language) nodes.

    One NL expression may generate multiple Python statements.
    Example: "load and preprocess data" might generate:
    - data = load_data('file.csv')
    - preprocessed = preprocess(data)

    We track the entire subtree and use semantic anchors for matching.
    """
    subtree_root_paths: List[str] = field(default_factory=list)
    subtree_ast_nodes: List[ast.AST] = field(default_factory=list)
    generated_code_span: Optional[Tuple[int, int]] = None  # (start_line, end_line)
    semantic_anchors: List[str] = field(default_factory=list)  # Variable names, keywords


@dataclass
class UnderspecNode:
    """
    Represents code that was generated but doesn't map back to spec.

    This occurs when:
    - LLM adds error handling not in spec
    - Helper functions generated
    - Implementation details not specified
    """
    ast_path: str
    ast_node: ast.AST
    context_ir_node_id: Optional[str]  # Nearest spec node
    reason: str


@dataclass
class EditInfo:
    """Information about an edit to an IR node."""
    edit_type: EditType
    node_id: str
    old_value: Any
    new_value: Any
    affects_usage: bool = False      # For HYBRID nodes
    affects_definition: bool = False  # For HYBRID nodes
    metadata: Dict[str, Any] = field(default_factory=dict)


class IRToPythonMapping:
    """
    Maintains forward mapping from IR nodes to Python AST.

    This is the primary mapping structure used during code generation
    and synchronization.
    """

    def __init__(self):
        # Primary mapping: IR node ID → list of Python AST paths
        self.ir_to_ast: Dict[str, List[str]] = {}

        # Category-specific mappings
        self.direct_mappings: Dict[str, str] = {}           # node_id → single AST path
        self.hybrid_mappings: Dict[str, HybridMapping] = {}  # node_id → HybridMapping
        self.nl_mappings: Dict[str, NLMapping] = {}         # node_id → NLMapping

        # Underspecification tracking
        self.unmapped_ast_paths: Set[str] = set()
        self.underspec_nodes: Dict[str, List[str]] = {}  # IR node → extra generated paths

        # Category tracking
        self.node_categories: Dict[str, MappingCategory] = {}

    def add_direct_mapping(self, node_id: str, ast_path: str):
        """Add a 1:1 mapping for a DIRECT node."""
        self.direct_mappings[node_id] = ast_path
        self.ir_to_ast[node_id] = [ast_path]
        self.node_categories[node_id] = MappingCategory.DIRECT

    def add_hybrid_mapping(self, node_id: str, mapping: HybridMapping):
        """Add a dual mapping for a HYBRID node."""
        self.hybrid_mappings[node_id] = mapping
        all_paths = mapping.usage_ast_paths + mapping.definition_ast_paths
        self.ir_to_ast[node_id] = all_paths
        self.node_categories[node_id] = MappingCategory.HYBRID

    def add_nl_mapping(self, node_id: str, mapping: NLMapping):
        """Add a many-to-many mapping for an NL node."""
        self.nl_mappings[node_id] = mapping
        self.ir_to_ast[node_id] = mapping.subtree_root_paths
        self.node_categories[node_id] = MappingCategory.NL

    def get_category(self, node_id: str) -> Optional[MappingCategory]:
        """Get the mapping category for a node."""
        return self.node_categories.get(node_id)

    def get_ast_paths(self, node_id: str) -> List[str]:
        """Get all AST paths for a node."""
        return self.ir_to_ast.get(node_id, [])

    def update_after_edit(self, node_id: str, new_paths: List[str]):
        """Update mapping after an edit."""
        old_paths = self.ir_to_ast.get(node_id, [])
        self.ir_to_ast[node_id] = new_paths

        # Update category-specific mappings
        category = self.node_categories.get(node_id)
        if category == MappingCategory.DIRECT and new_paths:
            self.direct_mappings[node_id] = new_paths[0]
        # For HYBRID and NL, caller should update specific mappings


class PythonToIRMapping:
    """
    Maintains reverse mapping from Python AST to IR nodes.

    This is used for code → spec synchronization (the PUT direction).
    """

    def __init__(self):
        # Primary reverse mapping: AST path → IR node ID
        self.ast_to_ir: Dict[str, str] = {}

        # For generated code: track which IR node generated it
        self.generated_code_map: Dict[str, str] = {}

        # Ownership tracking (for multi-statement NL)
        # One AST node might be influenced by multiple IR nodes
        self.ast_ownership: Dict[str, Set[str]] = {}

    def add_mapping(self, ast_path: str, node_id: str, is_generated: bool = False):
        """Add a reverse mapping from AST to IR."""
        self.ast_to_ir[ast_path] = node_id

        if is_generated:
            self.generated_code_map[ast_path] = node_id

        if ast_path not in self.ast_ownership:
            self.ast_ownership[ast_path] = set()
        self.ast_ownership[ast_path].add(node_id)

    def get_node_id(self, ast_path: str) -> Optional[str]:
        """Get the primary IR node for an AST path."""
        return self.ast_to_ir.get(ast_path)

    def is_generated(self, ast_path: str) -> bool:
        """Check if this AST node was generated (vs direct from spec)."""
        return ast_path in self.generated_code_map

    def get_owners(self, ast_path: str) -> Set[str]:
        """Get all IR nodes that contributed to this AST node."""
        return self.ast_ownership.get(ast_path, set())


@dataclass
class BidirectionalMapping:
    """Complete bidirectional mapping between IR and Python AST."""
    forward: IRToPythonMapping
    reverse: PythonToIRMapping
    underspec_nodes: List[UnderspecNode] = field(default_factory=list)

    def get_category(self, node_id: str) -> Optional[MappingCategory]:
        """Get mapping category for a node."""
        return self.forward.get_category(node_id)

    def is_underspecified(self, ast_path: str) -> bool:
        """Check if an AST path is underspecified (no IR mapping)."""
        return ast_path not in self.reverse.ast_to_ir


def compute_ast_path(node: ast.AST, parent_path: str = "") -> str:
    """
    Compute the path string for an AST node.

    Example: "body[0].body[1]" for second statement in first function.
    """
    # This is a simplified version - in practice, we'd traverse from root
    # For now, we use the node's position info if available
    if hasattr(node, '_path'):
        return node._path
    return parent_path


def enumerate_ast_paths(tree: ast.Module) -> List[Tuple[str, ast.AST]]:
    """
    Enumerate all AST nodes with their paths.

    Returns:
        List of (path, node) tuples
    """
    paths = []

    def visit(node: ast.AST, path: str):
        paths.append((path, node))

        # Visit children
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, ast.AST):
                        child_path = f"{path}.{field}[{i}]" if path else f"{field}[{i}]"
                        visit(item, child_path)
            elif isinstance(value, ast.AST):
                child_path = f"{path}.{field}" if path else field
                visit(value, child_path)

    visit(tree, "")
    return paths


def get_parent_path(path: str) -> Optional[str]:
    """
    Get the parent path of an AST path.

    Example: "body[0].body[1]" → "body[0]"
    """
    if '.' not in path:
        return None
    return path.rsplit('.', 1)[0]
