"""
MVP Parser for Semiformal Python Code

Implements fine-grained parsing into intent nodes with support for:
- Pure Python statements
- Natural language assignments
- Hole syntax: {} and {hint}
- Dependency tracking
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Set, Dict, Any


@dataclass
class IntentNode:
    """Represents a semantic unit in semiformal code"""
    id: str  # Unique node ID (e.g., "node_5_x", "node_7_nl_2")
    type: str  # 'identifier', 'operator', 'keyword', 'nl_phrase', 'python_expr', 'hole', 'function_call', 'expr_stmt'
    content: str  # The actual text content
    span: Tuple[int, int]  # Line span in semiformal code (start_line, end_line)
    dependencies: List[str] = field(default_factory=list)  # Node IDs this depends on
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata
    # Metadata keys for function_call and expr_stmt:
    # - 'full_statement': Complete statement code (for reconstruction)
    # - 'ast_node': Serialized AST for complex expressions
    # - 'args': List of argument nodes for function calls
    # - 'kwargs': Dict of keyword argument nodes for function calls
    # - 'num_args': Number of positional arguments
    # - 'num_kwargs': Number of keyword arguments


class SemiformalParser:
    """Parse semiformal code into intent nodes"""

    def __init__(self):
        self.nodes: List[IntentNode] = []
        self.defined_vars: Set[str] = set()
        self.defined_funcs: Set[str] = set()
        self.node_counter = 0

    def parse(self, code: str) -> List[IntentNode]:
        """
        Parse semiformal code into intent nodes.

        Returns:
            List of IntentNode objects
        """
        self.nodes = []
        self.defined_vars = set()
        self.defined_funcs = set()
        self.node_counter = 0

        # First, try to parse the entire code as Python
        try:
            tree = ast.parse(code)
            # It's valid Python - parse it
            for stmt in tree.body:
                line_num = getattr(stmt, 'lineno', 1) - 1
                self._parse_python_statement_node(stmt, line_num)
        except SyntaxError:
            # Fall back to line-by-line parsing for hybrid code
            # But first, try to identify and parse multiline statements
            lines = code.split('\n')
            i = 0
            
            while i < len(lines):
                line = lines[i]
                
                if not line.strip() or line.strip().startswith('#'):
                    i += 1
                    continue  # Skip empty lines and comments

                # Try to parse this line and accumulate following lines if needed
                accumulated = line
                start_line = i
                
                # Try parsing as Python first
                try:
                    tree = ast.parse(accumulated)
                    # It's valid Python - tokenize it
                    if tree.body:
                        self._parse_python_statement_node(tree.body[0], start_line)
                    i += 1
                except SyntaxError:
                    # Check if this might be a multiline statement
                    # Try accumulating more lines
                    multiline_parsed = False
                    
                    for j in range(i + 1, len(lines)):
                        accumulated += '\n' + lines[j]
                        try:
                            tree = ast.parse(accumulated)
                            if tree.body:
                                # Successfully parsed as multiline Python
                                self._parse_python_statement_node(tree.body[0], start_line)
                                i = j + 1
                                multiline_parsed = True
                                break
                        except SyntaxError:
                            continue
                    
                    if not multiline_parsed:
                        # It's NL or hybrid - parse specially
                        self._parse_nl_statement(line, start_line)
                        i += 1

        # Build dependency graph
        self._compute_dependencies()

        return self.nodes

    def _parse_python_statement_node(self, stmt: ast.AST, line_num: int):
        """Parse a Python AST statement node"""
        # Store the full statement code for later reconstruction
        full_code = ast.unparse(stmt)

        if isinstance(stmt, ast.Assign):
            self._parse_assignment(stmt, line_num)
        elif isinstance(stmt, ast.Expr):
            # Expression statement (e.g., standalone function call) - store full code
            expr_node = self._parse_expression(stmt.value, line_num, full_statement=full_code)
            # Also create an expr_stmt node to capture the complete statement
            if expr_node and isinstance(stmt.value, (ast.Call, ast.BinOp)):
                self._create_node(
                    node_type='expr_stmt',
                    content=full_code,
                    line_num=line_num,
                    metadata={
                        'full_statement': full_code,
                        'ast_type': type(stmt.value).__name__
                    }
                )
        elif isinstance(stmt, ast.FunctionDef):
            self._parse_function_def(stmt, line_num)
        elif isinstance(stmt, ast.Import) or isinstance(stmt, ast.ImportFrom):
            self._parse_import(stmt, line_num)
        else:
            # Generic statement - use ast.unparse
            self._create_node(
                node_type='python_stmt',
                content=full_code,
                line_num=line_num
            )

    def _parse_python_statement(self, tree: ast.AST, line: str, line_num: int):
        """Parse a valid Python statement into nodes"""
        if not tree.body:
            return

        stmt = tree.body[0]
        full_code = ast.unparse(stmt)

        if isinstance(stmt, ast.Assign):
            self._parse_assignment(stmt, line_num)
        elif isinstance(stmt, ast.Expr):
            # Expression statement - use same handling as _parse_python_statement_node
            expr_node = self._parse_expression(stmt.value, line_num, full_statement=full_code)
            if expr_node and isinstance(stmt.value, (ast.Call, ast.BinOp)):
                self._create_node(
                    node_type='expr_stmt',
                    content=full_code,
                    line_num=line_num,
                    metadata={
                        'full_statement': full_code,
                        'ast_type': type(stmt.value).__name__
                    }
                )
        elif isinstance(stmt, ast.FunctionDef):
            self._parse_function_def(stmt, line_num)
        elif isinstance(stmt, ast.Import) or isinstance(stmt, ast.ImportFrom):
            self._parse_import(stmt, line_num)
        else:
            # Generic statement
            self._create_node(
                node_type='python_stmt',
                content=line.strip(),
                line_num=line_num
            )

    def _parse_assignment(self, stmt: ast.Assign, line_num: int):
        """Parse assignment statement: x = value"""
        # For complete Python statements, store the full unparsed version
        full_code = ast.unparse(stmt)

        # Parse targets (LHS)
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                node = self._create_node(
                    node_type='identifier',
                    content=target.id,
                    line_num=line_num,
                    metadata={
                        'role': 'target',
                        'is_definition': True,
                        'full_statement': full_code  # Store full statement
                    }
                )
                self.defined_vars.add(target.id)
            elif isinstance(target, ast.Tuple):
                # Multiple assignment: x, y = ...
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        node = self._create_node(
                            node_type='identifier',
                            content=elt.id,
                            line_num=line_num,
                            metadata={
                                'role': 'target',
                                'is_definition': True,
                                'full_statement': full_code  # Store full statement
                            }
                        )
                        self.defined_vars.add(elt.id)

        # Parse value (RHS)
        self._parse_expression(stmt.value, line_num)

    def _parse_expression(self, expr: ast.AST, line_num: int, full_statement: str = None) -> Optional[IntentNode]:
        """Parse an expression recursively"""
        if isinstance(expr, ast.Name):
            # Variable reference
            return self._create_node(
                node_type='identifier',
                content=expr.id,
                line_num=line_num,
                metadata={'role': 'reference'}
            )

        elif isinstance(expr, ast.Call):
            # Function call - capture complete information
            func_name = None
            if isinstance(expr.func, ast.Name):
                func_name = expr.func.id
            elif isinstance(expr.func, ast.Attribute):
                # Method call like obj.method()
                func_name = ast.unparse(expr.func)
            else:
                func_name = ast.unparse(expr.func)

            # Parse positional arguments
            arg_nodes = []
            for arg in expr.args:
                arg_node = self._parse_expression(arg, line_num)
                if arg_node:
                    arg_nodes.append(arg_node.id)

            # Parse keyword arguments
            kwarg_nodes = {}
            for keyword in expr.keywords:
                if keyword.arg:  # Named keyword (not **kwargs)
                    kwarg_value_node = self._parse_expression(keyword.value, line_num)
                    if kwarg_value_node:
                        kwarg_nodes[keyword.arg] = kwarg_value_node.id

            # Create function call node with complete metadata
            func_node = self._create_node(
                node_type='function_call',
                content=func_name,
                line_num=line_num,
                metadata={
                    'num_args': len(expr.args),
                    'num_kwargs': len(expr.keywords),
                    'arg_node_ids': arg_nodes,
                    'kwarg_node_ids': kwarg_nodes,
                    'full_call': ast.unparse(expr),
                    'full_statement': full_statement or ast.unparse(expr)
                }
            )

            return func_node

        elif isinstance(expr, ast.Constant):
            # Literal value
            return self._create_node(
                node_type='literal',
                content=str(expr.value),
                line_num=line_num,
                metadata={'literal_type': type(expr.value).__name__}
            )

        elif isinstance(expr, ast.BinOp):
            # Binary operation: x + y
            self._parse_expression(expr.left, line_num)
            op_node = self._create_node(
                node_type='operator',
                content=self._get_operator_symbol(expr.op),
                line_num=line_num
            )
            self._parse_expression(expr.right, line_num)
            return op_node

        elif isinstance(expr, ast.List) or isinstance(expr, ast.Tuple):
            # List or tuple
            for elt in expr.elts:
                self._parse_expression(elt, line_num)

        elif isinstance(expr, ast.Dict):
            # Dictionary
            for key, value in zip(expr.keys, expr.values):
                if key:
                    self._parse_expression(key, line_num)
                self._parse_expression(value, line_num)

        # Add more expression types as needed
        return None

    def _parse_function_def(self, stmt: ast.FunctionDef, line_num: int):
        """Parse function definition"""
        # For complete function definitions, just store the whole thing
        func_code = ast.unparse(stmt)

        func_node = self._create_node(
            node_type='function_def',
            content=stmt.name,
            line_num=line_num,
            metadata={
                'params': [arg.arg for arg in stmt.args.args],
                'num_params': len(stmt.args.args),
                'full_code': func_code  # Store complete function code
            }
        )
        self.defined_funcs.add(stmt.name)

        # Parse parameters
        for arg in stmt.args.args:
            self._create_node(
                node_type='parameter',
                content=arg.arg,
                line_num=line_num,
                metadata={'function': stmt.name}
            )

    def _parse_import(self, stmt: ast.AST, line_num: int):
        """Parse import statement"""
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                self._create_node(
                    node_type='import',
                    content=alias.name,
                    line_num=line_num,
                    metadata={'as_name': alias.asname}
                )
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                self._create_node(
                    node_type='import_from',
                    content=alias.name,
                    line_num=line_num,
                    metadata={'module': stmt.module, 'as_name': alias.asname}
                )

    def _parse_nl_statement(self, line: str, line_num: int):
        """
        Parse natural language or hybrid statement.

        Supports:
        - x = natural language text
        - x = {}
        - x = {hint text}
        """
        if '=' not in line:
            # Pure NL comment or directive - skip for now
            return

        lhs, rhs = line.split('=', 1)
        lhs = lhs.strip()
        rhs = rhs.strip()

        # Parse LHS (target identifiers)
        targets = [t.strip() for t in lhs.split(',')]
        for target in targets:
            if target and target.isidentifier():
                self._create_node(
                    node_type='identifier',
                    content=target,
                    line_num=line_num,
                    metadata={'role': 'target', 'is_definition': True}
                )
                self.defined_vars.add(target)

        # Parse RHS
        # Check if it's a hole
        if rhs.startswith('{') and rhs.endswith('}'):
            hint = rhs[1:-1].strip()
            self._create_node(
                node_type='hole',
                content=hint,
                line_num=line_num,
                metadata={'has_hint': bool(hint)}
            )
        elif rhs == '...':
            # Ellipsis - treat as empty hole
            self._create_node(
                node_type='hole',
                content='',
                line_num=line_num,
                metadata={'has_hint': False}
            )
        else:
            # Natural language expression
            # Segment into semantic units
            nl_tokens = self._segment_nl_phrase(rhs)
            for i, token in enumerate[str](nl_tokens):
                self._create_node(
                    node_type='nl_phrase',
                    content=token,
                    line_num=line_num,
                    metadata={'phrase_index': i, 'phrase_count': len(nl_tokens)}
                )

    def _segment_nl_phrase(self, phrase: str) -> List[str]:
        """
        Segment NL phrase into semantic units.

        Uses a general approach without hardcoded keywords:
        1. Split on common prepositions and conjunctions
        2. Group remaining words into meaningful chunks

        Example: "split dataset into training and test sets"
        Returns: ["split dataset", "into", "training", "and", "test sets"]
        """
        if not phrase or not phrase.strip():
            return []

        # General linguistic markers (not domain-specific)
        markers = {
            'prepositions': ['into', 'from', 'to', 'with', 'by', 'for', 'using', 'via'],
            'conjunctions': ['and', 'or', 'but', 'then'],
            'articles': ['the', 'a', 'an'],
        }

        all_markers = set()
        for category in markers.values():
            all_markers.update(category)

        # Tokenize by markers while keeping them
        tokens = []
        words = phrase.split()

        if not words:
            return [phrase]

        current_chunk = []

        for word in words:
            word_lower = word.lower()

            if word_lower in all_markers:
                # Save current chunk if exists
                if current_chunk:
                    tokens.append(' '.join(current_chunk))
                    current_chunk = []

                # Add marker as separate token (unless it's an article)
                if word_lower not in markers['articles']:
                    tokens.append(word)
            else:
                current_chunk.append(word)

        # Add remaining chunk
        if current_chunk:
            tokens.append(' '.join(current_chunk))

        # If no segmentation happened, return whole phrase
        if not tokens or (len(tokens) == 1 and tokens[0] == phrase):
            # Try splitting on common patterns
            # Pattern: "verb object prep object" -> ["verb object", "prep object"]
            if len(words) >= 3:
                # Simple heuristic: split roughly in middle on markers
                mid = len(words) // 2
                for i in range(mid - 1, min(mid + 2, len(words))):
                    if i < len(words) and words[i].lower() in all_markers:
                        tokens = [
                            ' '.join(words[:i]),
                            ' '.join(words[i:])
                        ]
                        break

            # Final fallback: return whole phrase
            if not tokens or len(tokens) == 1:
                return [phrase]

        # Filter out empty tokens
        return [t for t in tokens if t.strip()]

    def _get_operator_symbol(self, op: ast.operator) -> str:
        """Get string representation of operator"""
        op_map = {
            ast.Add: '+',
            ast.Sub: '-',
            ast.Mult: '*',
            ast.Div: '/',
            ast.Mod: '%',
            ast.Pow: '**',
            ast.LShift: '<<',
            ast.RShift: '>>',
            ast.BitOr: '|',
            ast.BitXor: '^',
            ast.BitAnd: '&',
            ast.FloorDiv: '//',
        }
        return op_map.get(type(op), '?')

    def _create_node(
        self,
        node_type: str,
        content: str,
        line_num: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> IntentNode:
        """Create and register a new IntentNode"""
        node_id = f"node_{line_num}_{self.node_counter}"
        self.node_counter += 1

        node = IntentNode(
            id=node_id,
            type=node_type,
            content=content,
            span=(line_num, line_num),
            dependencies=[],
            metadata=metadata or {}
        )

        self.nodes.append(node)
        return node

    def _compute_dependencies(self):
        """Build dependency graph between nodes"""
        # Map variable/function names to their definition nodes
        definitions: Dict[str, IntentNode] = {}

        for node in self.nodes:
            if node.metadata.get('is_definition'):
                definitions[node.content] = node

        # Find references and link to definitions
        for node in self.nodes:
            if node.type == 'identifier' and node.metadata.get('role') == 'reference':
                # This is a reference to a variable
                if node.content in definitions:
                    def_node = definitions[node.content]
                    if def_node.id != node.id:  # Don't self-reference
                        node.dependencies.append(def_node.id)

            elif node.type == 'function_call':
                # This is a function call
                if node.content in self.defined_funcs:
                    # Find the function definition node
                    for def_node in self.nodes:
                        if def_node.type == 'function_def' and def_node.content == node.content:
                            node.dependencies.append(def_node.id)
                            break


def parse_semiformal(code: str) -> List[IntentNode]:
    """
    Convenience function to parse semiformal Python code.

    Args:
        code: Semiformal Python code

    Returns:
        List of IntentNode objects
    """
    parser = SemiformalParser()
    return parser.parse(code)
