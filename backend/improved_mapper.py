"""
Improved Content-Based Mapper

Fixes the broken tree mapping by using content-based matching instead
of pure structural similarity. This handles LLM-generated code that:
- Generates code in different order
- Has duplicate variable names
- Adds extra imports, functions, etc.

Strategy:
1. Find ALL AST nodes matching the IntentNode content
2. Use heuristics to pick the BEST match:
   - Prefer assignment targets (for variables being defined)
   - Prefer call sites (not function definitions)
   - Avoid matches inside function bodies (for main code)
   - Prefer matches closer to expected line number
"""

import ast
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class ASTMatch:
    """A potential match between IntentNode and AST node"""
    ast_node: ast.AST
    line: int
    context: str  # 'assignment_target', 'call_site', 'function_body', 'reference', etc.
    score: float  # Higher is better


class ImprovedContentMapper:
    """Maps IntentNodes to AST nodes using content-based matching"""

    def __init__(self, generated_code: str):
        self.code = generated_code
        self.code_lines = generated_code.split('\n')
        self.ast_tree = ast.parse(generated_code)

        # Build index of all identifiers and their contexts
        self.identifier_index: Dict[str, List[ASTMatch]] = {}
        self._build_identifier_index()

    def _build_identifier_index(self):
        """Build an index of all identifiers in the AST"""

        # Track which AST nodes are inside function definitions
        function_bodies = set()
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.FunctionDef):
                for child in ast.walk(node):
                    function_bodies.add(id(child))

        # Index all names
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.Name):
                name = node.id
                line = getattr(node, 'lineno', 0)

                # Determine context
                context = 'reference'
                if isinstance(node.ctx, ast.Store):
                    context = 'assignment_target'
                elif isinstance(node.ctx, ast.Load):
                    context = 'reference'

                # Check if inside function body
                if id(node) in function_bodies:
                    if context == 'assignment_target':
                        context = 'function_body_assignment'
                    else:
                        context = 'function_body_reference'

                match = ASTMatch(
                    ast_node=node,
                    line=line,
                    context=context,
                    score=0.0
                )

                if name not in self.identifier_index:
                    self.identifier_index[name] = []
                self.identifier_index[name].append(match)

            # Index function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    line = getattr(node, 'lineno', 0)

                    context = 'call_site'
                    if id(node) in function_bodies:
                        context = 'function_body_call'

                    match = ASTMatch(
                        ast_node=node,
                        line=line,
                        context=context,
                        score=0.0
                    )

                    if func_name not in self.identifier_index:
                        self.identifier_index[func_name] = []
                    self.identifier_index[func_name].append(match)

            # Index function definitions
            elif isinstance(node, ast.FunctionDef):
                func_name = node.name
                line = getattr(node, 'lineno', 0)

                match = ASTMatch(
                    ast_node=node,
                    line=line,
                    context='function_definition',
                    score=0.0
                )

                if func_name not in self.identifier_index:
                    self.identifier_index[func_name] = []
                self.identifier_index[func_name].append(match)

    def find_best_match(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMatch]:
        """
        Find the best AST node match for an IntentNode.

        Args:
            intent_node: The IntentNode to match
            expected_line: Expected line number (from semiformal), used as hint

        Returns:
            Best ASTMatch or None
        """
        content = intent_node.content
        node_type = intent_node.type

        # Get all potential matches
        if content not in self.identifier_index:
            return None

        candidates = self.identifier_index[content]

        if not candidates:
            return None

        # Score each candidate
        scored_candidates = []
        for candidate in candidates:
            score = self._score_match(intent_node, candidate, expected_line)
            scored_candidates.append((score, candidate))

        # Sort by score (highest first)
        scored_candidates.sort(reverse=True, key=lambda x: x[0])

        # Return best match
        if scored_candidates:
            best_score, best_match = scored_candidates[0]
            if best_score > 0:
                return best_match

        return None

    def _score_match(
        self,
        intent_node,
        ast_match: ASTMatch,
        expected_line: Optional[int]
    ) -> float:
        """
        Score how good a match is.

        Higher score = better match
        """
        score = 0.0

        node_type = intent_node.type
        node_role = intent_node.metadata.get('role', '')
        is_definition = intent_node.metadata.get('is_definition', False)

        # Rule 1: Match node type to context
        if node_type == 'identifier':
            if is_definition or node_role == 'target':
                # Looking for where variable is assigned
                if ast_match.context == 'assignment_target':
                    score += 100  # Strong preference
                elif ast_match.context == 'function_body_assignment':
                    score += 20   # Weak match (inside function)
                else:
                    score += 5    # Very weak
            else:
                # Looking for where variable is referenced
                if ast_match.context == 'reference':
                    score += 50
                elif ast_match.context == 'assignment_target':
                    score += 30  # Could be OK
                else:
                    score += 10

        elif node_type == 'function_call':
            # Looking for call site, not definition
            if ast_match.context == 'call_site':
                score += 100  # Strong preference
            elif ast_match.context == 'function_body_call':
                score += 30   # Inside function, less preferred
            elif ast_match.context == 'function_definition':
                score += 5    # We want call, not def

        elif node_type == 'function_def':
            # Looking for function definition
            if ast_match.context == 'function_definition':
                score += 100

        # Rule 2: Prefer main code over function bodies
        if 'function_body' not in ast_match.context:
            score += 50

        # Rule 3: Prefer matches closer to expected line
        if expected_line is not None and ast_match.line > 0:
            line_distance = abs(ast_match.line - expected_line)
            # Closer is better, but don't let this dominate
            proximity_score = max(0, 30 - line_distance)
            score += proximity_score

        # Rule 4: Avoid very early lines (imports, etc.) for main code
        if ast_match.line <= 5 and node_type == 'identifier' and is_definition:
            score -= 20  # Penalize mapping to imports/early stuff

        return score

    def map_intent_nodes(self, intent_nodes: List) -> Dict[str, Tuple[int, str]]:
        """
        Map all IntentNodes to AST locations.

        Returns:
            Dict[node_id] -> (line_number, code_snippet)
        """
        mappings = {}

        for node in intent_nodes:
            # Use semiformal line as hint
            expected_line = node.span[0] if hasattr(node, 'span') else None

            # Find best match
            best_match = self.find_best_match(node, expected_line)

            if best_match:
                line = best_match.line
                # Get code snippet
                if 1 <= line <= len(self.code_lines):
                    code_snippet = self.code_lines[line - 1].strip()
                else:
                    code_snippet = ""

                mappings[node.id] = (line, code_snippet)

        return mappings


def create_improved_mappings(intent_nodes: List, generated_code: str) -> List:
    """
    Create mappings using improved content-based algorithm.

    Handles:
    - Identifiers and function calls: content-based matching (accurate)
    - NL phrases and holes: map to the statement they're part of
    - expr_stmt: map to the actual statement

    Returns:
        List of Mapping objects (compatible with existing system)
    """
    from generator import Mapping, CodeSlice

    mapper = ImprovedContentMapper(generated_code)
    node_mappings = mapper.map_intent_nodes(intent_nodes)

    # Group nodes by semiformal line for fallback mapping
    nodes_by_line = {}
    for node in intent_nodes:
        line = node.span[0] if hasattr(node, 'span') else 0
        if line not in nodes_by_line:
            nodes_by_line[line] = []
        nodes_by_line[line].append(node)

    result = []
    for node in intent_nodes:
        if node.id in node_mappings:
            # Direct match found
            line, code_snippet = node_mappings[node.id]

            mapping = Mapping(
                node_id=node.id,
                slices=[CodeSlice(
                    code=code_snippet,
                    line_start=line,
                    line_end=line,
                    ast_nodes=[]
                )],
                confidence=0.9,  # High confidence for content-based match
                generation_method='content_based_match'
            )
            result.append(mapping)
        else:
            # No direct match - handle special cases
            node_type = node.type

            if node_type in ('nl_phrase', 'hole', 'expr_stmt'):
                # Map to the same location as other nodes on this line
                sf_line = node.span[0] if hasattr(node, 'span') else 0

                # Find a mapped node from the same semiformal line
                mapped_line = None
                mapped_snippet = None

                if sf_line in nodes_by_line:
                    for sibling in nodes_by_line[sf_line]:
                        if sibling.id in node_mappings and sibling.id != node.id:
                            mapped_line, mapped_snippet = node_mappings[sibling.id]
                            break

                if mapped_line:
                    # Use the same mapping as sibling nodes
                    mapping = Mapping(
                        node_id=node.id,
                        slices=[CodeSlice(
                            code=mapped_snippet,
                            line_start=mapped_line,
                            line_end=mapped_line,
                            ast_nodes=[]
                        )],
                        confidence=0.7,  # Lower confidence for inferred mapping
                        generation_method='inferred_from_siblings'
                    )
                    result.append(mapping)

    return result
