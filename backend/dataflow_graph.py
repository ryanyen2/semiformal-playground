"""
Data Flow Graph (DAG) for Dependency-Driven Code Generation

This module provides a generic, robust architecture for tracking data dependencies
and propagating changes through the computation graph. It replaces heuristic
approaches with a principled DAG-based system.

Core Concepts:
1. **DataFlowNode**: Represents any computational unit (variable, function call, expression)
2. **DataFlowGraph**: DAG of dependencies between nodes
3. **ChangeDetector**: Compares two graphs to identify structural changes
4. **UpdatePropagator**: Determines which nodes need regeneration based on DAG traversal

This system is:
- Generic: Works with any data types, no hardcoded schemas
- Robust: Handles arbitrary edits (add/remove/modify nodes, change dependencies)
- Extensible: Easy to add new node types or analysis strategies
- Principled: Based on graph theory, not heuristics
"""

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any, Tuple
from enum import Enum
from parser import IntentNode


class NodeKind(Enum):
    """Types of nodes in the data flow graph"""
    VARIABLE = "variable"           # Variable assignment target
    FUNCTION_CALL = "function_call" # Function call expression
    LITERAL = "literal"             # Literal value (string, number, etc.)
    PARAMETER = "parameter"         # Function parameter
    EXPRESSION = "expression"       # Generic expression
    IMPORT = "import"              # Import statement
    

class ChangeType(Enum):
    """Types of changes detected between graph versions"""
    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    NODE_MODIFIED = "node_modified"
    EDGE_ADDED = "edge_added"           # New dependency
    EDGE_REMOVED = "edge_removed"       # Dependency removed
    SUBGRAPH_REWIRED = "subgraph_rewired"  # Complex structural change


@dataclass
class DataFlowNode:
    """
    Represents a node in the data flow graph.
    
    Each node represents a computational unit with:
    - Unique identifier
    - Kind (variable, function call, etc.)
    - Value/content
    - Dependencies (incoming edges)
    - Dependents (outgoing edges)
    - Metadata for extensibility
    """
    id: str
    kind: NodeKind
    value: str  # The actual content (var name, function name, literal value, etc.)
    
    # Graph structure
    dependencies: Set[str] = field(default_factory=set)  # IDs of nodes this depends on
    dependents: Set[str] = field(default_factory=set)    # IDs of nodes that depend on this
    
    # Location in source
    line: int = 0
    col: int = 0
    
    # Type information (inferred, optional)
    inferred_type: Optional[str] = None
    
    # Generic metadata for extensibility
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Metadata examples:
    # - 'ast_node': Serialized AST node
    # - 'intent_node_id': Link to original IntentNode
    # - 'function_args': List of argument node IDs
    # - 'function_kwargs': Dict of kwarg name -> node ID
    # - 'is_definition': Whether this defines a new function/variable
    # - 'scope': Scope information
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, DataFlowNode):
            return False
        return self.id == other.id


@dataclass
class Change:
    """Represents a single change between two graph versions"""
    change_type: ChangeType
    node_id: Optional[str] = None
    old_node: Optional[DataFlowNode] = None
    new_node: Optional[DataFlowNode] = None
    affected_edge: Optional[Tuple[str, str]] = None  # (source_id, target_id)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdateSpec:
    """
    Specification for what needs to be updated/regenerated.
    
    This is the output of the UpdatePropagator and input to the code generator.
    It tells the generator which functions need regeneration and what context to use.
    """
    nodes_to_regenerate: List[str] = field(default_factory=list)  # Node IDs
    regeneration_order: List[str] = field(default_factory=list)   # Topological order
    node_contexts: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # node_id -> context
    changes: List[Change] = field(default_factory=list)


class DataFlowGraph:
    """
    Directed Acyclic Graph (DAG) representing data flow and dependencies.
    
    The graph captures:
    - All computational units (variables, function calls, expressions)
    - Dependencies between units (who depends on whom)
    - Scope information
    - Type information (inferred)
    
    This is a generic representation that works for any code, not just specific datasets.
    """
    
    def __init__(self):
        self.nodes: Dict[str, DataFlowNode] = {}  # node_id -> node
        self.roots: Set[str] = set()  # Nodes with no dependencies (e.g., imports, literals)
        self.leaves: Set[str] = set()  # Nodes with no dependents
        self.function_defs: Dict[str, str] = {}  # function_name -> node_id mapping
        self.function_calls: Dict[str, List[str]] = {}  # function_name -> list of call node_ids
        
    def add_node(self, node: DataFlowNode):
        """Add a node to the graph"""
        self.nodes[node.id] = node
        
        # Track function definitions (actual function def statements, not variables)
        if node.metadata.get('is_function_definition'):
            func_name = node.value
            self.function_defs[func_name] = node.id
        
        # Track function calls
        if node.kind == NodeKind.FUNCTION_CALL and not node.metadata.get('is_function_definition'):
            func_name = node.value
            if func_name not in self.function_calls:
                self.function_calls[func_name] = []
            self.function_calls[func_name].append(node.id)
        
        # Update roots/leaves
        if not node.dependencies:
            self.roots.add(node.id)
        if not node.dependents:
            self.leaves.add(node.id)
    
    def add_edge(self, from_id: str, to_id: str):
        """
        Add a dependency edge: to_id depends on from_id.
        
        Args:
            from_id: Source node (provider)
            to_id: Target node (consumer)
        """
        if from_id not in self.nodes or to_id not in self.nodes:
            return
        
        self.nodes[from_id].dependents.add(to_id)
        self.nodes[to_id].dependencies.add(from_id)
        
        # Update roots/leaves
        if to_id in self.roots:
            self.roots.remove(to_id)
        if from_id in self.leaves:
            self.leaves.remove(from_id)
    
    def get_dependencies(self, node_id: str, recursive: bool = False) -> Set[str]:
        """
        Get all dependencies of a node.
        
        Args:
            node_id: Node to query
            recursive: If True, get transitive closure of dependencies
            
        Returns:
            Set of node IDs
        """
        if node_id not in self.nodes:
            return set()
        
        if not recursive:
            return self.nodes[node_id].dependencies.copy()
        
        # DFS to get transitive closure
        visited = set()
        stack = [node_id]
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            
            if current in self.nodes:
                stack.extend(self.nodes[current].dependencies)
        
        visited.discard(node_id)  # Don't include the node itself
        return visited
    
    def get_dependents(self, node_id: str, recursive: bool = False) -> Set[str]:
        """
        Get all nodes that depend on this node.
        
        Args:
            node_id: Node to query
            recursive: If True, get transitive closure of dependents
            
        Returns:
            Set of node IDs
        """
        if node_id not in self.nodes:
            return set()
        
        if not recursive:
            return self.nodes[node_id].dependents.copy()
        
        # DFS to get transitive closure
        visited = set()
        stack = [node_id]
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            
            if current in self.nodes:
                stack.extend(self.nodes[current].dependents)
        
        visited.discard(node_id)
        return visited
    
    def topological_sort(self, node_ids: Optional[Set[str]] = None) -> List[str]:
        """
        Return nodes in topological order (dependencies before dependents).
        
        Args:
            node_ids: If provided, only sort these nodes (useful for partial updates)
            
        Returns:
            List of node IDs in topological order
        """
        if node_ids is None:
            node_ids = set(self.nodes.keys())
        
        # Kahn's algorithm
        in_degree = {nid: len(self.nodes[nid].dependencies & node_ids) 
                    for nid in node_ids if nid in self.nodes}
        
        queue = [nid for nid in node_ids if in_degree.get(nid, 0) == 0]
        result = []
        
        while queue:
            current = queue.pop(0)
            result.append(current)
            
            if current not in self.nodes:
                continue
            
            for dependent in self.nodes[current].dependents:
                if dependent not in node_ids:
                    continue
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        return result
    
    def get_node(self, node_id: str) -> Optional[DataFlowNode]:
        """Get a node by ID"""
        return self.nodes.get(node_id)
    
    def has_cycle(self) -> bool:
        """Check if the graph has cycles (shouldn't happen for valid code)"""
        visited = set()
        rec_stack = set()
        
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            
            if node_id in self.nodes:
                for dep in self.nodes[node_id].dependents:
                    if dep not in visited:
                        if dfs(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            
            rec_stack.remove(node_id)
            return False
        
        for node_id in self.nodes:
            if node_id not in visited:
                if dfs(node_id):
                    return True
        
        return False


class GraphBuilder:
    """
    Builds a DataFlowGraph from IntentNodes (parsed semiformal code).
    
    This is a generic builder that works with any code structure.
    It extracts data flow relationships without assuming specific schemas or datasets.
    """
    
    def __init__(self):
        self.graph = DataFlowGraph()
        self.node_id_map: Dict[str, str] = {}  # intent_node_id -> graph_node_id
        
    def build_from_intent_nodes(self, intent_nodes: List[IntentNode]) -> DataFlowGraph:
        """
        Build data flow graph from intent nodes.
        
        Args:
            intent_nodes: Parsed intent nodes from semiformal code
            
        Returns:
            DataFlowGraph representing dependencies
        """
        self.graph = DataFlowGraph()
        self.node_id_map = {}
        
        # Phase 1: Create nodes
        for intent_node in intent_nodes:
            self._create_graph_node(intent_node)
        
        # Phase 2: Create edges from dependencies
        for intent_node in intent_nodes:
            self._create_edges(intent_node)
        
        return self.graph
    
    def _create_graph_node(self, intent_node: IntentNode):
        """Create a DataFlowNode from an IntentNode"""
        # Map intent node type to graph node kind
        kind = self._infer_node_kind(intent_node)
        
        # Extract additional metadata for function definitions
        metadata = {
            'intent_node_id': intent_node.id,
            'intent_type': intent_node.type,
            **intent_node.metadata
        }
        
        # Mark function definitions and extract parameters
        if intent_node.type == 'function_def':
            metadata['is_definition'] = True
            metadata['is_function_definition'] = True  # More specific flag
            # Extract parameter names from full_code or dependencies
            params = []
            if 'full_code' in intent_node.metadata:
                # Parse parameters from function signature
                params = self._extract_params_from_signature(intent_node.metadata['full_code'])
            elif 'params' in intent_node.metadata:
                params = intent_node.metadata['params']
            metadata['parameters'] = params
        
        graph_node = DataFlowNode(
            id=intent_node.id,
            kind=kind,
            value=intent_node.content,
            line=intent_node.span[0],
            metadata=metadata
        )
        
        self.graph.add_node(graph_node)
        self.node_id_map[intent_node.id] = intent_node.id
    
    def _extract_params_from_signature(self, func_code: str) -> List[str]:
        """Extract parameter names from function definition"""
        try:
            import ast
            tree = ast.parse(func_code)
            if tree.body and isinstance(tree.body[0], ast.FunctionDef):
                func_def = tree.body[0]
                return [arg.arg for arg in func_def.args.args]
        except:
            pass
        return []
    
    def _infer_node_kind(self, intent_node: IntentNode) -> NodeKind:
        """Infer the graph node kind from intent node type"""
        type_map = {
            'identifier': NodeKind.VARIABLE,
            'function_call': NodeKind.FUNCTION_CALL,
            'function_def': NodeKind.FUNCTION_CALL,  # Function definitions as a special kind
            'literal': NodeKind.LITERAL,
            'nl_phrase': NodeKind.EXPRESSION,
            'hole': NodeKind.EXPRESSION,
            'expr_stmt': NodeKind.EXPRESSION,
            'python_expr': NodeKind.EXPRESSION,
            'parameter': NodeKind.PARAMETER,
        }
        
        return type_map.get(intent_node.type, NodeKind.EXPRESSION)
    
    def _create_edges(self, intent_node: IntentNode):
        """Create dependency edges based on IntentNode dependencies"""
        if intent_node.id not in self.node_id_map:
            return
        
        to_id = self.node_id_map[intent_node.id]
        
        # Add edges from dependencies
        for dep_id in intent_node.dependencies:
            if dep_id in self.node_id_map:
                from_id = self.node_id_map[dep_id]
                self.graph.add_edge(from_id, to_id)
        
        # Link function calls to their definitions
        if intent_node.type == 'function_call':
            func_name = intent_node.content
            if func_name in self.graph.function_defs:
                func_def_id = self.graph.function_defs[func_name]
                # Add edge: function call depends on function definition
                self.graph.add_edge(func_def_id, to_id)
        
        # Link function calls to their definitions
        if intent_node.type == 'function_call':
            func_name = intent_node.content
            if func_name in self.graph.function_defs:
                func_def_id = self.graph.function_defs[func_name]
                # Add edge: function call depends on function definition
                self.graph.add_edge(func_def_id, to_id)


class ChangeDetector:
    """
    Detects changes between two versions of a DataFlowGraph.
    
    This is the core algorithm for understanding what changed:
    - Structural changes (nodes added/removed/modified)
    - Dependency changes (edges added/removed)
    - Complex rewiring (multiple changes affecting a subgraph)
    
    Output: List of Change objects describing the diff
    """
    
    def detect_changes(
        self,
        old_graph: Optional[DataFlowGraph],
        new_graph: DataFlowGraph
    ) -> List[Change]:
        """
        Detect changes between old and new graph.
        
        Args:
            old_graph: Previous version (None if this is the first version)
            new_graph: Current version
            
        Returns:
            List of Change objects
        """
        changes = []
        
        if old_graph is None:
            # Everything is new
            for node_id in new_graph.nodes:
                changes.append(Change(
                    change_type=ChangeType.NODE_ADDED,
                    node_id=node_id,
                    new_node=new_graph.nodes[node_id]
                ))
            return changes
        
        old_ids = set(old_graph.nodes.keys())
        new_ids = set(new_graph.nodes.keys())
        
        # Detect node additions
        for node_id in new_ids - old_ids:
            changes.append(Change(
                change_type=ChangeType.NODE_ADDED,
                node_id=node_id,
                new_node=new_graph.nodes[node_id]
            ))
        
        # Detect node removals
        for node_id in old_ids - new_ids:
            changes.append(Change(
                change_type=ChangeType.NODE_REMOVED,
                node_id=node_id,
                old_node=old_graph.nodes[node_id]
            ))
        
        # Detect node modifications and edge changes
        for node_id in old_ids & new_ids:
            old_node = old_graph.nodes[node_id]
            new_node = new_graph.nodes[node_id]
            
            # Check if node content changed
            if self._node_modified(old_node, new_node):
                changes.append(Change(
                    change_type=ChangeType.NODE_MODIFIED,
                    node_id=node_id,
                    old_node=old_node,
                    new_node=new_node
                ))
            
            # Check for edge changes (dependency changes)
            old_deps = old_node.dependencies
            new_deps = new_node.dependencies
            
            # New dependencies
            for dep_id in new_deps - old_deps:
                changes.append(Change(
                    change_type=ChangeType.EDGE_ADDED,
                    affected_edge=(dep_id, node_id),
                    metadata={'dependency': dep_id, 'dependent': node_id}
                ))
            
            # Removed dependencies
            for dep_id in old_deps - new_deps:
                changes.append(Change(
                    change_type=ChangeType.EDGE_REMOVED,
                    affected_edge=(dep_id, node_id),
                    metadata={'dependency': dep_id, 'dependent': node_id}
                ))
        
        return changes
    
    def _node_modified(self, old_node: DataFlowNode, new_node: DataFlowNode) -> bool:
        """Check if a node was modified (content/value changed)"""
        # Check basic properties
        if (old_node.value != new_node.value or
            old_node.kind != new_node.kind or
            old_node.metadata.get('full_statement') != new_node.metadata.get('full_statement')):
            return True
        
        # Check function signature changes (parameters added/removed/reordered)
        if old_node.metadata.get('is_definition'):
            old_params = old_node.metadata.get('parameters', [])
            new_params = new_node.metadata.get('parameters', [])
            if old_params != new_params:
                return True
        
        return False


class UpdatePropagator:
    """
    Determines what needs to be regenerated based on changes to the DAG.
    
    Core algorithm:
    1. Identify directly affected nodes (nodes that changed)
    2. Propagate impact through the DAG (find all dependents)
    3. Build UpdateSpec with:
       - Nodes to regenerate
       - Topological order for regeneration
       - Context for each node (what it depends on)
    
    This is the "smart" part that replaces heuristics with principled graph traversal.
    """
    
    def compute_update_spec(
        self,
        changes: List[Change],
        graph: DataFlowGraph
    ) -> UpdateSpec:
        """
        Compute what needs to be updated based on changes.
        
        Args:
            changes: List of detected changes
            graph: Current data flow graph
            
        Returns:
            UpdateSpec describing what to regenerate
        """
        spec = UpdateSpec(changes=changes)
        
        # Collect directly affected nodes
        affected_nodes = set()
        signature_changed_functions = set()  # Track functions whose signatures changed
        
        for change in changes:
            if change.change_type in (ChangeType.NODE_ADDED, ChangeType.NODE_MODIFIED):
                if change.node_id:
                    affected_nodes.add(change.node_id)
                    
                    # Check if this is a function definition with signature change
                    if change.new_node and change.new_node.metadata.get('is_definition'):
                        func_name = change.new_node.value
                        old_params = change.old_node.metadata.get('parameters', []) if change.old_node else []
                        new_params = change.new_node.metadata.get('parameters', [])
                        if old_params != new_params:
                            signature_changed_functions.add(func_name)
                            # Add metadata about signature change
                            change.metadata['signature_changed'] = True
                            change.metadata['old_params'] = old_params
                            change.metadata['new_params'] = new_params
            
            elif change.change_type == ChangeType.EDGE_ADDED:
                # New dependency added - need to regenerate the dependent
                if change.affected_edge:
                    _, dependent_id = change.affected_edge
                    affected_nodes.add(dependent_id)
            
            elif change.change_type == ChangeType.EDGE_REMOVED:
                # Dependency removed - need to regenerate the dependent
                if change.affected_edge:
                    _, dependent_id = change.affected_edge
                    affected_nodes.add(dependent_id)
        
        # For function signature changes, also mark all call sites for regeneration
        for func_name in signature_changed_functions:
            if func_name in graph.function_calls:
                for call_node_id in graph.function_calls[func_name]:
                    affected_nodes.add(call_node_id)
        
        # Propagate to all transitive dependents
        nodes_to_regenerate = set(affected_nodes)
        for node_id in affected_nodes:
            dependents = graph.get_dependents(node_id, recursive=True)
            nodes_to_regenerate.update(dependents)
        
        spec.nodes_to_regenerate = list(nodes_to_regenerate)
        
        # Compute topological order for regeneration
        spec.regeneration_order = graph.topological_sort(nodes_to_regenerate)
        
        # Build context for each node
        for node_id in nodes_to_regenerate:
            spec.node_contexts[node_id] = self._build_node_context(node_id, graph)
        
        return spec
    
    def _build_node_context(self, node_id: str, graph: DataFlowGraph) -> Dict[str, Any]:
        """
        Build generation context for a specific node.
        
        Context includes:
        - Direct dependencies (what this node uses)
        - Dependency values/types
        - Metadata from the node itself
        
        This is generic - no hardcoded schemas or assumptions.
        """
        node = graph.get_node(node_id)
        if not node:
            return {}
        
        context = {
            'node_id': node_id,
            'kind': node.kind.value,
            'value': node.value,
            'line': node.line,
            'metadata': node.metadata.copy(),
            'dependencies': [],
            'dependency_info': {}
        }
        
        # Add information about each dependency
        for dep_id in node.dependencies:
            dep_node = graph.get_node(dep_id)
            if dep_node:
                context['dependencies'].append(dep_id)
                context['dependency_info'][dep_id] = {
                    'kind': dep_node.kind.value,
                    'value': dep_node.value,
                    'type': dep_node.inferred_type,
                    'metadata': dep_node.metadata
                }
        
        return context
