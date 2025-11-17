"""
Node Completeness Classification

Classifies IR nodes to determine appropriate edit handling:
- COMPLETE: Full Python code → Direct AST edits
- INCOMPLETE: Partial Python (e.g., call without def) → Hybrid approach
- NL: Natural language → LLM regeneration
"""

from enum import Enum
from typing import List, Set
from parser import IntentNode


class NodeCompleteness(Enum):
    """Classification of node completeness"""
    COMPLETE = "complete"        # Complete Python: print(x), x=5, defined functions
    INCOMPLETE = "incomplete"    # Incomplete: foo() call without def, holes
    NL = "nl"                    # Natural language expressions


class CompletenessClassifier:
    """
    Classifies nodes by completeness to determine edit strategy.

    Key insight: Same edit has different handling based on completeness:
    - COMPLETE nodes → Direct AST manipulation
    - INCOMPLETE nodes → Hybrid (direct on usage, LLM on definition)
    - NL nodes → LLM regeneration only
    """

    def __init__(self, nodes: List[IntentNode]):
        """
        Initialize classifier with all nodes.

        Args:
            nodes: All intent nodes from parsed spec
        """
        self.nodes = nodes
        self._build_symbol_tables()

    def _build_symbol_tables(self):
        """Build tables of defined functions and variables"""
        self.defined_functions: Set[str] = set()
        self.defined_variables: Set[str] = set()

        # Built-in functions
        self.builtin_functions = {
            'print', 'len', 'str', 'int', 'float', 'list', 'dict', 'set',
            'range', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'sum',
            'max', 'min', 'abs', 'round', 'all', 'any', 'open', 'input'
        }

        # Scan for defined functions and variables
        for node in self.nodes:
            if node.type == 'function_def':
                self.defined_functions.add(node.content)
            elif node.type == 'identifier' and 'assignment' in node.metadata.get('context', ''):
                self.defined_variables.add(node.content)

    def classify(self, node: IntentNode) -> NodeCompleteness:
        """
        Classify a single node's completeness.

        Args:
            node: IntentNode to classify

        Returns:
            NodeCompleteness enum value
        """
        # Natural language or holes
        if node.type in ('nl_phrase', 'hole'):
            return NodeCompleteness.NL

        # Function calls
        if node.type == 'function_call':
            func_name = node.content

            # Builtin or defined → Complete
            if func_name in self.builtin_functions or func_name in self.defined_functions:
                return NodeCompleteness.COMPLETE
            else:
                # Undefined function → Incomplete (call exists, no body)
                return NodeCompleteness.INCOMPLETE

        # Function definitions
        if node.type == 'function_def':
            # Check if body is complete (not just pass/...)
            has_complete_body = node.metadata.get('has_body', False)
            if has_complete_body:
                return NodeCompleteness.COMPLETE
            else:
                return NodeCompleteness.INCOMPLETE

        # Expression statements
        if node.type == 'expr_stmt':
            # Check if it's a Python statement or contains NL/holes
            full_statement = node.metadata.get('full_statement', '')
            if '{' in full_statement:  # Contains hole
                return NodeCompleteness.INCOMPLETE
            # Further check could parse to see if valid Python
            return NodeCompleteness.COMPLETE

        # Identifiers, literals, operators
        if node.type in ('identifier', 'literal', 'operator'):
            return NodeCompleteness.COMPLETE

        # Python expressions
        if node.type == 'python_expr':
            # These are complete Python by definition
            return NodeCompleteness.COMPLETE

        # Default to incomplete for safety
        return NodeCompleteness.INCOMPLETE

    def classify_line(self, line_num: int) -> NodeCompleteness:
        """
        Classify all nodes on a line and return overall completeness.

        Rules:
        - If any node is NL → line is NL
        - If all nodes are COMPLETE → line is COMPLETE
        - Otherwise → line is INCOMPLETE

        Args:
            line_num: Line number in spec

        Returns:
            Overall completeness for the line
        """
        line_nodes = [n for n in self.nodes if n.span[0] == line_num]

        if not line_nodes:
            return NodeCompleteness.COMPLETE

        classifications = [self.classify(node) for node in line_nodes]

        # Any NL makes entire line NL
        if any(c == NodeCompleteness.NL for c in classifications):
            return NodeCompleteness.NL

        # All complete → line is complete
        if all(c == NodeCompleteness.COMPLETE for c in classifications):
            return NodeCompleteness.COMPLETE

        # Mixed or incomplete → line is incomplete
        return NodeCompleteness.INCOMPLETE

    def get_edit_strategy(self, affected_nodes: List[IntentNode]) -> str:
        """
        Determine edit strategy based on affected nodes' completeness.

        Args:
            affected_nodes: Nodes affected by an edit

        Returns:
            'direct', 'hybrid', or 'llm'
        """
        if not affected_nodes:
            return 'direct'

        classifications = [self.classify(node) for node in affected_nodes]

        # All complete → Direct AST manipulation
        if all(c == NodeCompleteness.COMPLETE for c in classifications):
            return 'direct'

        # Any NL → LLM regeneration
        if any(c == NodeCompleteness.NL for c in classifications):
            return 'llm'

        # Has incomplete (e.g., function call without def) → Hybrid
        if any(c == NodeCompleteness.INCOMPLETE for c in classifications):
            return 'hybrid'

        return 'llm'  # Default to LLM for safety

    def get_nodes_by_line(self, line_num: int) -> List[IntentNode]:
        """Get all nodes on a specific line"""
        return [n for n in self.nodes if n.span[0] == line_num]

    def find_definition_for_call(self, call_node: IntentNode) -> IntentNode | None:
        """
        Find the function definition node for a function call.

        Args:
            call_node: Function call node

        Returns:
            Corresponding function definition node, or None if not found
        """
        if call_node.type != 'function_call':
            return None

        func_name = call_node.content

        for node in self.nodes:
            if node.type == 'function_def' and node.content == func_name:
                return node

        return None


def classify_edit_scenario(
    old_code: str,
    new_code: str,
    old_nodes: List[IntentNode],
    new_nodes: List[IntentNode]
) -> dict:
    """
    Analyze an edit scenario to determine handling strategy.

    Returns dict with:
    - strategy: 'direct', 'hybrid', or 'llm'
    - affected_lines: List of changed line numbers
    - completeness_changes: Dict of line → (old_completeness, new_completeness)
    - reason: Explanation of strategy choice
    """
    from difflib import unified_diff

    old_lines = old_code.split('\n')
    new_lines = new_code.split('\n')

    # Find changed lines
    diff = list(unified_diff(old_lines, new_lines, lineterm=''))
    changed_lines = set()

    for line in diff:
        if line.startswith('@@'):
            # Parse line numbers from @@ -old +new @@
            import re
            match = re.search(r'@@ -(\d+),?\d* \+(\d+),?\d* @@', line)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(2))
                changed_lines.add(old_line)
                changed_lines.add(new_line)

    # Classify completeness
    old_classifier = CompletenessClassifier(old_nodes)
    new_classifier = CompletenessClassifier(new_nodes)

    completeness_changes = {}
    for line in changed_lines:
        old_comp = old_classifier.classify_line(line)
        new_comp = new_classifier.classify_line(line)
        completeness_changes[line] = (old_comp, new_comp)

    # Determine overall strategy
    strategies = []
    for old_comp, new_comp in completeness_changes.values():
        # If either old or new is NL → LLM
        if old_comp == NodeCompleteness.NL or new_comp == NodeCompleteness.NL:
            strategies.append('llm')
        # Both complete → Direct
        elif old_comp == NodeCompleteness.COMPLETE and new_comp == NodeCompleteness.COMPLETE:
            strategies.append('direct')
        # Otherwise → Hybrid
        else:
            strategies.append('hybrid')

    # Overall strategy: most conservative
    if 'llm' in strategies:
        overall = 'llm'
        reason = "Contains natural language or incomplete Python requiring LLM"
    elif 'hybrid' in strategies:
        overall = 'hybrid'
        reason = "Contains incomplete Python (e.g., function call without definition)"
    else:
        overall = 'direct'
        reason = "All affected code is complete Python - can use direct AST edit"

    return {
        'strategy': overall,
        'affected_lines': list(changed_lines),
        'completeness_changes': completeness_changes,
        'reason': reason
    }
