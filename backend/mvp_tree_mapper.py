"""
Tree-Based Mapping Algorithm for IR to AST

Implements a formalized, generalizable algorithm for mapping semiformal IR nodes
to generated Python AST nodes using:
- Tree structure comparison
- Subtree similarity metrics
- Optimal alignment via dynamic programming
- Token-level mapping within matched subtrees
- Underspecification detection

Based on techniques from program synthesis and tree edit distance.
"""

import ast
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set
from enum import Enum


@dataclass
class TreeNode:
    """Unified tree node representation"""
    node_type: str  # e.g., 'function_def', 'assignment', 'call', etc.
    content: str  # Primary content (name, operator, etc.)
    children: List['TreeNode'] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    source_node: Optional[any] = None  # Original IR node or AST node
    
    # Location information
    line: int = 0
    col: int = 0
    
    # Computed properties
    subtree_size: int = 1  # Number of nodes in subtree
    depth: int = 0  # Depth in tree
    
    def compute_size(self) -> int:
        """Recursively compute subtree size"""
        self.subtree_size = 1 + sum(child.compute_size() for child in self.children)
        return self.subtree_size
    
    def compute_depth(self, d: int = 0):
        """Recursively set depth for all nodes"""
        self.depth = d
        for child in self.children:
            child.compute_depth(d + 1)


@dataclass
class SubtreeMapping:
    """Represents a mapping between IR subtree and AST subtree"""
    ir_root: TreeNode
    ast_root: TreeNode
    similarity: float  # 0.0 to 1.0
    token_mappings: List[Tuple[TreeNode, TreeNode]] = field(default_factory=list)
    confidence: float = 1.0
    is_underspecified: bool = False  # True if AST has more detail than IR


class MappingType(Enum):
    """Type of mapping relationship"""
    EXACT = "exact"  # Perfect structural and content match
    STRUCTURAL = "structural"  # Structure matches, content may differ
    SEMANTIC = "semantic"  # Semantic equivalence (e.g., NL -> code)
    PARTIAL = "partial"  # Only partial overlap
    UNMAPPED = "unmapped"  # No mapping found


@dataclass
class TreeMapping:
    """Complete mapping information"""
    ir_node: TreeNode
    ast_node: Optional[TreeNode]
    mapping_type: MappingType
    similarity: float
    confidence: float
    token_level_mappings: List[Tuple[TreeNode, TreeNode]] = field(default_factory=list)


class TreeMapper:
    """
    Maps semiformal IR tree to Python AST tree using structural similarity.
    
    Key algorithm: Two-phase matching
    1. Coarse-grained: Match major subtrees (functions, statements)
    2. Fine-grained: Match tokens within subtrees
    """
    
    def __init__(self):
        # Similarity threshold for considering a match
        self.similarity_threshold = 0.6
        
        # Cache for computed similarities
        self._similarity_cache: Dict[Tuple[int, int], float] = {}
    
    def build_ir_tree(self, intent_nodes: List) -> TreeNode:
        """
        Build tree structure from flat list of IntentNodes.
        
        Strategy:
        1. Group by statements (top-level constructs)
        2. Build hierarchy based on containment and dependencies
        3. Normalize to common tree representation
        """
        from mvp_parser import IntentNode
        
        if not intent_nodes:
            return TreeNode(node_type='module', content='<root>')
        
        root = TreeNode(node_type='module', content='<root>')
        
        # Group nodes by line to identify statements
        lines: Dict[int, List[IntentNode]] = {}
        for node in intent_nodes:
            line = node.span[0]
            if line not in lines:
                lines[line] = []
            lines[line].append(node)
        
        # Process each line as a statement
        for line_num in sorted(lines.keys()):
            line_nodes = lines[line_num]
            stmt_node = self._build_statement_node(line_nodes, line_num)
            if stmt_node:
                root.children.append(stmt_node)
        
        root.compute_size()
        root.compute_depth()
        return root
    
    def _build_statement_node(self, nodes: List, line_num: int) -> Optional[TreeNode]:
        """Build a statement-level tree node from intent nodes"""
        from mvp_parser import IntentNode
        
        if not nodes:
            return None
        
        # Identify statement type
        func_defs = [n for n in nodes if n.type == 'function_def']
        func_calls = [n for n in nodes if n.type == 'function_call']
        assignments = [n for n in nodes if n.type == 'identifier' and n.metadata.get('is_definition')]
        holes = [n for n in nodes if n.type == 'hole']
        nl_phrases = [n for n in nodes if n.type == 'nl_phrase']
        
        # Function definition
        if func_defs:
            func = func_defs[0]
            stmt = TreeNode(
                node_type='function_def',
                content=func.content,
                line=line_num,
                source_node=func,
                metadata={'params': func.metadata.get('params', [])}
            )
            # Add parameters as children
            params = [n for n in nodes if n.type == 'parameter']
            for param in params:
                stmt.children.append(TreeNode(
                    node_type='parameter',
                    content=param.content,
                    source_node=param
                ))
            return stmt
        
        # Assignment or expression statement
        if assignments or func_calls:
            # Determine if it's an assignment
            if assignments:
                stmt = TreeNode(
                    node_type='assignment',
                    content='=',
                    line=line_num,
                    source_node=assignments[0]
                )
                
                # LHS: targets
                for target in assignments:
                    stmt.children.append(TreeNode(
                        node_type='target',
                        content=target.content,
                        source_node=target
                    ))
                
                # RHS: build expression tree
                rhs_nodes = [n for n in nodes if n not in assignments]
                if holes:
                    # Hole assignment
                    hole = holes[0]
                    rhs = TreeNode(
                        node_type='hole',
                        content=hole.content,
                        source_node=hole,
                        metadata={'is_underspecified': True}
                    )
                    stmt.children.append(rhs)
                elif nl_phrases:
                    # NL phrase assignment
                    rhs = TreeNode(
                        node_type='nl_expression',
                        content=' '.join(p.content for p in nl_phrases),
                        source_node=nl_phrases[0],
                        metadata={'is_underspecified': True, 'nl_parts': nl_phrases}
                    )
                    stmt.children.append(rhs)
                elif func_calls:
                    # Function call
                    rhs = self._build_call_node(func_calls[0], nodes)
                    stmt.children.append(rhs)
                else:
                    # Other expression
                    rhs = self._build_expression_tree(rhs_nodes)
                    if rhs:
                        stmt.children.append(rhs)
                
                return stmt
            
            # Expression statement (standalone call)
            if func_calls:
                return self._build_call_node(func_calls[0], nodes)
        
        # Generic statement
        if nodes:
            return TreeNode(
                node_type='statement',
                content=' '.join(n.content for n in nodes[:3]),  # First few nodes
                line=line_num,
                source_node=nodes[0]
            )
        
        return None
    
    def _build_call_node(self, func_call_node, all_nodes: List) -> TreeNode:
        """Build function call tree node"""
        call = TreeNode(
            node_type='call',
            content=func_call_node.content,
            source_node=func_call_node
        )
        
        # Add arguments as children
        arg_node_ids = func_call_node.metadata.get('arg_node_ids', [])
        for arg_id in arg_node_ids:
            # Find the argument node
            arg_node = next((n for n in all_nodes if n.id == arg_id), None)
            if arg_node:
                call.children.append(TreeNode(
                    node_type='argument',
                    content=arg_node.content,
                    source_node=arg_node
                ))
        
        return call
    
    def _build_expression_tree(self, nodes: List) -> Optional[TreeNode]:
        """Build expression tree from nodes"""
        if not nodes:
            return None
        
        # Simple expression building - can be enhanced
        operators = [n for n in nodes if n.type == 'operator']
        
        if operators:
            # Binary operation
            op = operators[0]
            expr = TreeNode(
                node_type='binop',
                content=op.content,
                source_node=op
            )
            
            # Add operands
            other_nodes = [n for n in nodes if n.type != 'operator']
            for node in other_nodes[:2]:  # Left and right operands
                expr.children.append(TreeNode(
                    node_type='value',
                    content=node.content,
                    source_node=node
                ))
            
            return expr
        
        # Single value
        if nodes:
            return TreeNode(
                node_type='value',
                content=nodes[0].content,
                source_node=nodes[0]
            )
        
        return None
    
    def build_ast_tree(self, python_code: str) -> TreeNode:
        """
        Build normalized tree from Python AST.
        
        Converts Python AST to our unified TreeNode representation.
        """
        try:
            tree = ast.parse(python_code)
        except SyntaxError:
            return TreeNode(node_type='module', content='<root>')
        
        root = TreeNode(node_type='module', content='<root>')
        
        for stmt in tree.body:
            stmt_node = self._ast_to_tree(stmt)
            if stmt_node:
                root.children.append(stmt_node)
        
        root.compute_size()
        root.compute_depth()
        return root
    
    def _ast_to_tree(self, node: ast.AST) -> Optional[TreeNode]:
        """Convert AST node to TreeNode recursively"""
        
        # Function definition
        if isinstance(node, ast.FunctionDef):
            tree_node = TreeNode(
                node_type='function_def',
                content=node.name,
                line=node.lineno,
                col=node.col_offset,
                source_node=node
            )
            
            # Add parameters
            for arg in node.args.args:
                tree_node.children.append(TreeNode(
                    node_type='parameter',
                    content=arg.arg,
                    source_node=arg
                ))
            
            # Add body statements
            for stmt in node.body:
                child = self._ast_to_tree(stmt)
                if child:
                    tree_node.children.append(child)
            
            return tree_node
        
        # Assignment
        elif isinstance(node, ast.Assign):
            tree_node = TreeNode(
                node_type='assignment',
                content='=',
                line=node.lineno,
                col=node.col_offset,
                source_node=node
            )
            
            # Targets
            for target in node.targets:
                if isinstance(target, ast.Name):
                    tree_node.children.append(TreeNode(
                        node_type='target',
                        content=target.id,
                        source_node=target
                    ))
            
            # Value
            value_node = self._ast_expr_to_tree(node.value)
            if value_node:
                tree_node.children.append(value_node)
            
            return tree_node
        
        # Expression statement
        elif isinstance(node, ast.Expr):
            return self._ast_expr_to_tree(node.value)
        
        # Return, If, While, etc.
        elif isinstance(node, (ast.Return, ast.If, ast.While, ast.For)):
            tree_node = TreeNode(
                node_type=node.__class__.__name__.lower(),
                content=node.__class__.__name__,
                line=node.lineno,
                col=node.col_offset,
                source_node=node
            )
            # Add relevant child expressions
            return tree_node
        
        # Import
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            tree_node = TreeNode(
                node_type='import',
                content='import',
                line=node.lineno,
                source_node=node
            )
            return tree_node
        
        return None
    
    def _ast_expr_to_tree(self, node: ast.AST) -> Optional[TreeNode]:
        """Convert AST expression to TreeNode"""
        
        # Function call
        if isinstance(node, ast.Call):
            func_name = self._get_call_name(node)
            tree_node = TreeNode(
                node_type='call',
                content=func_name,
                line=getattr(node, 'lineno', 0),
                col=getattr(node, 'col_offset', 0),
                source_node=node
            )
            
            # Add arguments
            for arg in node.args:
                arg_node = self._ast_expr_to_tree(arg)
                if arg_node:
                    tree_node.children.append(arg_node)
            
            return tree_node
        
        # Name (variable reference)
        elif isinstance(node, ast.Name):
            return TreeNode(
                node_type='name',
                content=node.id,
                line=node.lineno,
                col=node.col_offset,
                source_node=node
            )
        
        # Constant/Literal
        elif isinstance(node, ast.Constant):
            return TreeNode(
                node_type='constant',
                content=str(node.value),
                line=node.lineno,
                col=node.col_offset,
                source_node=node
            )
        
        # Binary operation
        elif isinstance(node, ast.BinOp):
            op_str = self._get_binop_str(node.op)
            tree_node = TreeNode(
                node_type='binop',
                content=op_str,
                line=node.lineno,
                col=node.col_offset,
                source_node=node
            )
            
            left = self._ast_expr_to_tree(node.left)
            right = self._ast_expr_to_tree(node.right)
            
            if left:
                tree_node.children.append(left)
            if right:
                tree_node.children.append(right)
            
            return tree_node
        
        # List, Tuple, Dict
        elif isinstance(node, (ast.List, ast.Tuple)):
            tree_node = TreeNode(
                node_type='list' if isinstance(node, ast.List) else 'tuple',
                content='[]' if isinstance(node, ast.List) else '()',
                source_node=node
            )
            for elt in node.elts:
                elt_node = self._ast_expr_to_tree(elt)
                if elt_node:
                    tree_node.children.append(elt_node)
            return tree_node
        
        return None
    
    def _get_call_name(self, node: ast.Call) -> str:
        """Extract function name from Call node"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return ast.unparse(node.func)
        else:
            return ast.unparse(node.func)
    
    def _get_binop_str(self, op: ast.operator) -> str:
        """Get string representation of binary operator"""
        op_map = {
            ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
            ast.Mod: '%', ast.Pow: '**', ast.FloorDiv: '//'
        }
        return op_map.get(type(op), '?')
    
    def compute_similarity(self, ir_node: TreeNode, ast_node: TreeNode) -> float:
        """
        Compute similarity between two tree nodes.
        
        Combines multiple similarity metrics:
        1. Node type similarity
        2. Content similarity (token matching)
        3. Structural similarity (children pattern)
        4. Context similarity (parent/siblings)
        
        Returns: Similarity score in [0, 1]
        """
        # Check cache
        cache_key = (id(ir_node), id(ast_node))
        if cache_key in self._similarity_cache:
            return self._similarity_cache[cache_key]
        
        # 1. Node type similarity
        type_sim = self._node_type_similarity(ir_node, ast_node)
        
        # 2. Content similarity
        content_sim = self._content_similarity(ir_node, ast_node)
        
        # 3. Structural similarity (children)
        struct_sim = self._structural_similarity(ir_node, ast_node)
        
        # Weighted combination
        similarity = (
            0.4 * type_sim +
            0.4 * content_sim +
            0.2 * struct_sim
        )
        
        # Cache result
        self._similarity_cache[cache_key] = similarity
        
        return similarity
    
    def _node_type_similarity(self, ir_node: TreeNode, ast_node: TreeNode) -> float:
        """Compare node types"""
        # Direct match
        if ir_node.node_type == ast_node.node_type:
            return 1.0
        
        # Compatible types
        compatible_types = {
            ('call', 'call'): 1.0,
            ('function_def', 'function_def'): 1.0,
            ('assignment', 'assignment'): 1.0,
            ('nl_expression', 'call'): 0.7,  # NL might become function call
            ('nl_expression', 'binop'): 0.7,  # NL might become operation
            ('nl_expression', 'name'): 0.6,   # NL might become variable
            ('hole', 'call'): 0.8,             # Hole filled with call
            ('hole', 'name'): 0.8,             # Hole filled with name
            ('hole', 'constant'): 0.8,         # Hole filled with constant
        }
        
        key = (ir_node.node_type, ast_node.node_type)
        if key in compatible_types:
            return compatible_types[key]
        
        # No match
        return 0.0
    
    def _content_similarity(self, ir_node: TreeNode, ast_node: TreeNode) -> float:
        """Compare node content (tokens)"""
        ir_content = ir_node.content.lower().strip()
        ast_content = ast_node.content.lower().strip()
        
        # Exact match
        if ir_content == ast_content:
            return 1.0
        
        # Empty content
        if not ir_content or not ast_content:
            return 0.0
        
        # Token overlap (Jaccard similarity)
        ir_tokens = set(ir_content.split())
        ast_tokens = set(ast_content.split())
        
        if not ir_tokens or not ast_tokens:
            # Use character-level similarity for short strings
            return self._string_similarity(ir_content, ast_content)
        
        intersection = ir_tokens & ast_tokens
        union = ir_tokens | ast_tokens
        
        jaccard = len(intersection) / len(union) if union else 0.0
        
        return jaccard
    
    def _string_similarity(self, s1: str, s2: str) -> float:
        """Character-level edit distance similarity"""
        if s1 == s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        # Levenshtein distance (simple version)
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i-1] == s2[j-1]:
                    dp[i][j] = dp[i-1][j-1]
                else:
                    dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
        
        distance = dp[m][n]
        max_len = max(m, n)
        similarity = 1.0 - (distance / max_len)
        
        return max(0.0, similarity)
    
    def _structural_similarity(self, ir_node: TreeNode, ast_node: TreeNode) -> float:
        """Compare structural patterns (number and types of children)"""
        ir_children = len(ir_node.children)
        ast_children = len(ast_node.children)
        
        # If both have no children
        if ir_children == 0 and ast_children == 0:
            return 1.0
        
        # If one has children and other doesn't
        if (ir_children == 0) != (ast_children == 0):
            # Special case: IR might be underspecified
            if ir_children == 0 and ast_children > 0:
                # AST has more detail - this is expected for underspecification
                return 0.5
            return 0.3
        
        # Compare child counts
        count_sim = 1.0 - abs(ir_children - ast_children) / max(ir_children, ast_children)
        
        # Compare child types
        ir_child_types = [c.node_type for c in ir_node.children]
        ast_child_types = [c.node_type for c in ast_node.children]
        
        # Type overlap
        ir_types_set = set(ir_child_types)
        ast_types_set = set(ast_child_types)
        
        if ir_types_set or ast_types_set:
            type_sim = len(ir_types_set & ast_types_set) / len(ir_types_set | ast_types_set)
        else:
            type_sim = 1.0
        
        return 0.6 * count_sim + 0.4 * type_sim
    
    def find_best_match(
        self,
        ir_node: TreeNode,
        ast_candidates: List[TreeNode]
    ) -> Tuple[Optional[TreeNode], float]:
        """
        Find the best matching AST node for an IR node.
        
        Returns: (best_match, similarity_score)
        """
        if not ast_candidates:
            return None, 0.0
        
        best_match = None
        best_similarity = 0.0
        
        for ast_node in ast_candidates:
            similarity = self.compute_similarity(ir_node, ast_node)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = ast_node
        
        # Only return if above threshold
        if best_similarity >= self.similarity_threshold:
            return best_match, best_similarity
        
        return None, best_similarity
    
    def align_subtrees(
        self,
        ir_root: TreeNode,
        ast_root: TreeNode
    ) -> List[TreeMapping]:
        """
        Align IR subtree with AST subtree using dynamic programming.
        
        This is the core mapping algorithm:
        1. Top-down matching of major structures
        2. Bottom-up alignment of tokens
        3. DP for optimal matching when structure differs
        
        Returns: List of TreeMapping objects
        """
        mappings: List[TreeMapping] = []
        
        # Match roots first
        root_similarity = self.compute_similarity(ir_root, ast_root)
        
        if root_similarity >= self.similarity_threshold:
            # Roots match - create mapping
            mapping = TreeMapping(
                ir_node=ir_root,
                ast_node=ast_root,
                mapping_type=self._determine_mapping_type(root_similarity),
                similarity=root_similarity,
                confidence=root_similarity
            )
            mappings.append(mapping)
            
            # Recursively align children
            child_mappings = self._align_children(ir_root, ast_root)
            mappings.extend(child_mappings)
        else:
            # Roots don't match well - try to match descendants
            # This handles structural differences
            mappings.extend(self._align_mismatched_subtrees(ir_root, ast_root))
        
        return mappings
    
    def _align_children(
        self,
        ir_parent: TreeNode,
        ast_parent: TreeNode
    ) -> List[TreeMapping]:
        """Align children of matched parent nodes"""
        mappings: List[TreeMapping] = []
        
        ir_children = ir_parent.children
        ast_children = ast_parent.children
        
        if not ir_children:
            # IR has no children, but AST might
            # Mark AST children as underspecified
            for ast_child in ast_children:
                mappings.append(TreeMapping(
                    ir_node=ir_parent,  # Map to parent
                    ast_node=ast_child,
                    mapping_type=MappingType.PARTIAL,
                    similarity=0.5,
                    confidence=0.5
                ))
            return mappings
        
        if not ast_children:
            # AST has no children but IR does - unusual
            for ir_child in ir_children:
                mappings.append(TreeMapping(
                    ir_node=ir_child,
                    ast_node=None,
                    mapping_type=MappingType.UNMAPPED,
                    similarity=0.0,
                    confidence=0.0
                ))
            return mappings
        
        # Both have children - use DP alignment
        # Simple greedy approach: match each IR child to best AST child
        used_ast = set()
        
        for ir_child in ir_children:
            available_ast = [a for a in ast_children if id(a) not in used_ast]
            best_match, similarity = self.find_best_match(ir_child, available_ast)
            
            if best_match:
                mapping = TreeMapping(
                    ir_node=ir_child,
                    ast_node=best_match,
                    mapping_type=self._determine_mapping_type(similarity),
                    similarity=similarity,
                    confidence=similarity
                )
                mappings.append(mapping)
                used_ast.add(id(best_match))
                
                # Recursively align their children
                if ir_child.children or best_match.children:
                    child_mappings = self._align_children(ir_child, best_match)
                    mappings.extend(child_mappings)
            else:
                # No good match found
                mappings.append(TreeMapping(
                    ir_node=ir_child,
                    ast_node=None,
                    mapping_type=MappingType.UNMAPPED,
                    similarity=0.0,
                    confidence=0.0
                ))
        
        # Handle unused AST children (underspecified in IR)
        for ast_child in ast_children:
            if id(ast_child) not in used_ast:
                mappings.append(TreeMapping(
                    ir_node=ir_parent,  # Best effort: link to parent
                    ast_node=ast_child,
                    mapping_type=MappingType.PARTIAL,
                    similarity=0.3,
                    confidence=0.3
                ))
        
        return mappings
    
    def _align_mismatched_subtrees(
        self,
        ir_root: TreeNode,
        ast_root: TreeNode
    ) -> List[TreeMapping]:
        """
        Handle case where root nodes don't match.
        Try to find correspondences at deeper levels.
        """
        mappings: List[TreeMapping] = []
        
        # Collect all descendants
        ir_descendants = self._collect_descendants(ir_root)
        ast_descendants = self._collect_descendants(ast_root)
        
        used_ast = set()
        
        # Try to match IR nodes to AST descendants
        for ir_node in [ir_root] + ir_descendants:
            best_match, similarity = self.find_best_match(
                ir_node,
                [n for n in ([ast_root] + ast_descendants) if id(n) not in used_ast]
            )
            
            if best_match:
                mapping = TreeMapping(
                    ir_node=ir_node,
                    ast_node=best_match,
                    mapping_type=self._determine_mapping_type(similarity),
                    similarity=similarity,
                    confidence=similarity * 0.8  # Lower confidence for mismatched structure
                )
                mappings.append(mapping)
                used_ast.add(id(best_match))
        
        return mappings
    
    def _collect_descendants(self, node: TreeNode) -> List[TreeNode]:
        """Collect all descendant nodes"""
        descendants = []
        for child in node.children:
            descendants.append(child)
            descendants.extend(self._collect_descendants(child))
        return descendants
    
    def _determine_mapping_type(self, similarity: float) -> MappingType:
        """Determine mapping type based on similarity score"""
        if similarity >= 0.95:
            return MappingType.EXACT
        elif similarity >= 0.8:
            return MappingType.STRUCTURAL
        elif similarity >= 0.6:
            return MappingType.SEMANTIC
        elif similarity >= 0.3:
            return MappingType.PARTIAL
        else:
            return MappingType.UNMAPPED
    
    def map_trees(
        self,
        ir_tree: TreeNode,
        ast_tree: TreeNode
    ) -> List[TreeMapping]:
        """
        Main entry point: Map IR tree to AST tree.
        
        Returns: Complete list of TreeMapping objects
        """
        # Clear cache for new mapping
        self._similarity_cache.clear()
        
        # Align the trees
        mappings = self.align_subtrees(ir_tree, ast_tree)
        
        return mappings
    
    def detect_underspecified_regions(
        self,
        ast_tree: TreeNode,
        mappings: List[TreeMapping]
    ) -> List[TreeNode]:
        """
        Detect AST nodes that have no corresponding IR node.
        These represent code generated from underspecified parts (NL, holes).
        """
        # Collect all mapped AST nodes
        mapped_ast_ids = set()
        for mapping in mappings:
            if mapping.ast_node:
                mapped_ast_ids.add(id(mapping.ast_node))
        
        # Find unmapped AST nodes
        all_ast_nodes = [ast_tree] + self._collect_descendants(ast_tree)
        underspecified = []
        
        for ast_node in all_ast_nodes:
            if id(ast_node) not in mapped_ast_ids:
                underspecified.append(ast_node)
        
        return underspecified


class MappingAdapter:
    """
    Adapts tree-based mappings to the existing Mapping/CodeSlice format
    for backward compatibility.
    """
    
    @staticmethod
    def convert_tree_mappings_to_code_mappings(
        tree_mappings: List[TreeMapping],
        generated_code: str
    ) -> List:
        """
        Convert TreeMapping objects to Mapping objects.
        
        Args:
            tree_mappings: List of TreeMapping from tree mapper
            generated_code: The generated Python code
            
        Returns:
            List of Mapping objects compatible with existing system
        """
        from mvp_generator import Mapping, CodeSlice
        
        code_lines = generated_code.split('\n')
        result_mappings = []
        
        for tree_mapping in tree_mappings:
            # Skip unmapped nodes
            if tree_mapping.mapping_type == MappingType.UNMAPPED:
                continue
            
            # Get the original IR node
            ir_node = tree_mapping.ir_node
            ast_node = tree_mapping.ast_node
            
            if not ast_node or not ast_node.source_node:
                continue
            
            # Extract source node info
            source_ir = ir_node.source_node
            if not source_ir:
                continue
            
            # Get AST node location
            ast_source = ast_node.source_node
            if not isinstance(ast_source, ast.AST):
                continue
            
            # Extract line and column info
            line_start = getattr(ast_source, 'lineno', 1)
            line_end = getattr(ast_source, 'end_lineno', line_start)
            col_offset = getattr(ast_source, 'col_offset', 0)
            
            # Extract code snippet
            code_snippet = MappingAdapter._extract_code_snippet(
                generated_code, line_start, line_end
            )
            
            # Create CodeSlice
            code_slice = CodeSlice(
                code=code_snippet,
                line_start=line_start,
                line_end=line_end,
                ast_nodes=[ast_source]
            )
            
            # Determine generation method
            generation_method = MappingAdapter._map_type_to_method(tree_mapping.mapping_type)
            
            # Create Mapping
            mapping = Mapping(
                node_id=source_ir.id if hasattr(source_ir, 'id') else f"node_{id(source_ir)}",
                slices=[code_slice],
                confidence=tree_mapping.confidence,
                generation_method=generation_method
            )
            
            result_mappings.append(mapping)
        
        return result_mappings
    
    @staticmethod
    def _extract_code_snippet(code: str, line_start: int, line_end: int) -> str:
        """Extract code snippet from line range"""
        lines = code.split('\n')
        if line_start < 1:
            line_start = 1
        if line_end > len(lines):
            line_end = len(lines)
        
        snippet_lines = lines[line_start-1:line_end]
        return '\n'.join(snippet_lines).strip()
    
    @staticmethod
    def _map_type_to_method(mapping_type: MappingType) -> str:
        """Map MappingType to generation method string"""
        mapping = {
            MappingType.EXACT: 'exact_match',
            MappingType.STRUCTURAL: 'structural_match',
            MappingType.SEMANTIC: 'semantic_match',
            MappingType.PARTIAL: 'partial_match',
            MappingType.UNMAPPED: 'unmapped'
        }
        return mapping.get(mapping_type, 'unknown')

