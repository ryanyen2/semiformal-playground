"""
MVP Code Generator

Single LLM call code generation:
- Full code generation from scratch
- Git diff format generation for edits
- Annotated semiformal code with parsed nodes as context
"""

import os
import ast
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set
from parser import IntentNode
from config import MVPConfig, DEFAULT_CONFIG
from llm_service import LLMService
from postprocessing import CodePostprocessor


# ============================================================================
# Preprocessing: Text-Based Annotated Semiformal Code
# ============================================================================

def create_annotated_semiformal_text(
    parsed_nodes: List[IntentNode],
    original_semiformal_text: str
) -> str:
    """
    Convert parsed nodes into annotated text format with anchor comments.
    
    Input: List of parsed nodes (IntentNode objects)
    Output: Text with anchor comments above each line
    
    Example:
        Input nodes on line 1: [identifier "result", nl_phrase "load", ...]
        Output:
            # result; load; dataset; process it
            result = load the dataset and process it
    """
    # Group nodes by line number
    lines_dict = group_nodes_by_line(parsed_nodes)
    
    # Get original lines
    original_lines = original_semiformal_text.split('\n')
    
    # Build annotated output
    annotated_lines = []
    
    # Process all lines in order, adding anchor comments only for lines with nodes
    for line_num in range(len(original_lines)):
        # Check if this line has nodes
        if line_num in lines_dict:
            nodes_on_line = lines_dict[line_num]
            
            # Extract anchors from nodes on this line
            anchors = extract_anchors_from_nodes(nodes_on_line, original_lines[line_num])
            
            # Add anchor comment if we have anchors
            if anchors:
                # Use special anchor syntax so we can reliably detect anchors later
                anchor_comment = "#> " + "; ".join(anchors)
                annotated_lines.append(anchor_comment)
        
        # Add original statement (always include, even if no nodes)
        annotated_lines.append(original_lines[line_num])
        
        # Add blank line for readability (only if not last line)
        if line_num < len(original_lines) - 1:
            annotated_lines.append("")
    
    # Join and clean up trailing newlines
    result = "\n".join(annotated_lines).rstrip()
    
    return result


def group_nodes_by_line(parsed_nodes: List[IntentNode]) -> Dict[int, List[IntentNode]]:
    """Group nodes by their line number (0-indexed from span[0])"""
    lines = {}
    
    for node in parsed_nodes:
        line_num = node.span[0]  # span is (start_line, end_line), 0-indexed
        
        if line_num not in lines:
            lines[line_num] = []
        
        lines[line_num].append(node)
    
    return lines


def extract_anchors_from_nodes(
    nodes: List[IntentNode],
    original_line_text: str = ""
) -> List[str]:
    """
    Extract anchor strings from nodes on a single line.
    
    Order: left to right based on position in original text (leaf to root typically).
    
    Edge cases handled:
    - Duplicate anchors: deduplicated
    - All trivial nl_phrases: include at least one phrase if all are trivial
    """
    anchors = []
    seen_anchors = set()  # Avoid duplicates
    
    # Sort nodes by their position in the original line text
    # If we can't find position, use the order they appear
    nodes_with_pos = []
    for node in nodes:
        # Try to find column position in original line
        col_pos = find_node_column_position(node, original_line_text)
        nodes_with_pos.append((col_pos, node))
    
    # Sort by column position (left to right)
    nodes_sorted = sorted(nodes_with_pos, key=lambda x: x[0])
    
    # Track nl_phrase nodes separately for edge case
    nl_phrase_nodes = []
    
    # First pass: collect all anchors that pass node_to_anchor filter
    for col_pos, node in nodes_sorted:
        anchor_text = node_to_anchor(node)
        
        if anchor_text and anchor_text not in seen_anchors:
            anchors.append(anchor_text)
            seen_anchors.add(anchor_text)
        
        # Track nl_phrase nodes for edge case handling
        if node.type == "nl_phrase":
            nl_phrase_nodes.append((col_pos, node))
    
    # Edge case: If all nl_phrases were trivial (none added to anchors),
    # but we have nl_phrase nodes, include at least one
    if nl_phrase_nodes:
        has_nl_phrase_anchor = any(
            node.type == "nl_phrase" and node.content in seen_anchors
            for _, node in nodes_sorted
        )
        
        if not has_nl_phrase_anchor:
            # Include the first nl_phrase even if trivial
            first_col_pos, first_nl_phrase = nl_phrase_nodes[0]
            if first_nl_phrase.content not in seen_anchors:
                # Insert at appropriate position to maintain left-to-right order
                insert_pos = len(anchors)
                for i, anchor in enumerate(anchors):
                    # Find the node that produced this anchor
                    for col_pos, node in nodes_sorted:
                        if node_to_anchor(node) == anchor and col_pos > first_col_pos:
                            insert_pos = i
                            break
                    if insert_pos < len(anchors):
                        break
                
                anchors.insert(insert_pos, first_nl_phrase.content)
                seen_anchors.add(first_nl_phrase.content)
    
    return anchors


def find_node_column_position(node: IntentNode, line_text: str) -> int:
    """
    Find the column position of a node's content in the original line text.
    
    Returns column position, or 9999 if not found (to sort to end).
    """
    if not line_text:
        return 9999
    
    content = node.content
    
    # Try exact match first
    pos = line_text.find(content)
    if pos >= 0:
        return pos
    
    # Try case-insensitive match
    pos = line_text.lower().find(content.lower())
    if pos >= 0:
        return pos
    
    # Try finding partial match (for multi-word content)
    if ' ' in content:
        first_word = content.split()[0]
        pos = line_text.find(first_word)
        if pos >= 0:
            return pos
    
    # Not found - return large number to sort to end
    return 9999


def node_to_anchor(node: IntentNode) -> Optional[str]:
    """
    Convert a single node to its anchor string representation.
    
    Returns None if the node should not be included as an anchor.
    """
    node_type = node.type
    value = node.content
    metadata = node.metadata
    
    # Trivial words to skip for nl_phrase
    trivial_words = {"the", "a", "an", "and", "or", "it", "is"}
    
    if node_type == "identifier":
        role = metadata.get("role")
        if role == "target":
            return value
        elif role == "reference":
            # Include references that are function arguments or important
            # Skip if redundant (e.g., already have target with same name)
            return value
    
    elif node_type == "nl_phrase":
        # Skip trivial connectives
        phrase = value.strip().lower()
        if phrase in trivial_words:
            return None  # Skip
        return value
    
    elif node_type == "hole":
        # Use the entire hint text
        return value
    
    elif node_type == "function_call":
        # Use function name
        return value
    
    elif node_type == "expr_stmt":
        # Skip expression statements (they're parent nodes)
        return None
    
    elif node_type == "function_def":
        # Include function definitions
        return value
    
    # Skip other types
    return None


def get_original_statement(line_num: int, original_text: str) -> str:
    """Extract the original statement text for a given line (0-indexed)"""
    lines = original_text.split('\n')
    
    if line_num < len(lines):
        return lines[line_num]
    
    return ""


@dataclass
class CodeSlice:
    """Represents a slice of generated Python code"""
    code: str
    line_start: int
    line_end: int
    ast_nodes: List[ast.AST] = field(default_factory=list)


@dataclass
class Mapping:
    """Maps intent nodes to generated code slices"""
    node_id: str
    slices: List[CodeSlice]
    confidence: float  # 0.0 to 1.0
    generation_method: str  # 'direct', 'llm_generated', 'template', 'placeholder'


@dataclass
class FunctionSignature:
    """Represents a function signature extracted from a call"""
    name: str
    positional_args: List[str]
    keyword_args: Dict[str, str]
    call_node_id: str


class CodeGenerator:
    """Generate Python code from intent nodes"""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        config: Optional[MVPConfig] = None,
        generate_implementations: bool = True
    ):
        """
        Initialize code generator.

        Args:
            openai_api_key: OpenAI API key (or use OPENAI_API_KEY env var)
            config: Configuration object (uses DEFAULT_CONFIG if None)
            generate_implementations: Whether to generate implementations for undefined functions
        """
        self.config = config or DEFAULT_CONFIG
        self.generate_implementations = generate_implementations
        self.llm_service = LLMService(openai_api_key, config)
        self.postprocessor = CodePostprocessor()
    
    @staticmethod
    def _extract_imports(code: str) -> List[str]:
        """Extract all top-level import statements from code."""
        imports = []
        try:
            tree = ast.parse(code)
            # Only get top-level imports (from tree.body, not from nested scopes)
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.append(ast.unparse(node))
        except:
            # Fallback: use regex for imports
            import_pattern = r'^(import\s+\S+|from\s+\S+\s+import\s+[^\n]+)'
            for line in code.split('\n'):
                match = re.match(import_pattern, line.strip())
                if match:
                    imports.append(match.group(1))
        return imports
    
    @staticmethod
    def _remove_imports_from_code(code: str) -> str:
        """Remove all top-level import statements from code, returning the rest."""
        lines = []
        try:
            tree = ast.parse(code)
            # Only remove top-level imports
            for node in tree.body:
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    lines.append(ast.unparse(node))
        except:
            # Fallback: use regex
            import_pattern = r'^(import\s+\S+|from\s+\S+\s+import\s+[^\n]+)'
            for line in code.split('\n'):
                if not re.match(import_pattern, line.strip()):
                    lines.append(line)
        return '\n'.join(lines)
    

    def generate_with_mapping(
        self,
        nodes: List[IntentNode],
        context: str = "",
        existing_python: str = "",
        focus_nodes: Optional[List[IntentNode]] = None,
        trigger_type: str = "initial",
        previous_semiformal: str = ""
    ) -> Tuple[str, List[Mapping]]:
        """
        Generate Python code from intent nodes using single LLM call.

        Args:
            nodes: List of intent nodes from parser
            context: Original semiformal code for context
            existing_python: Existing Python code (empty for full generation)

        Returns:
            (generated_code, mappings)
        """
        # Annotate semiformal code with parsed nodes
        annotated_semiformal = self._annotate_semiformal_with_nodes(context, nodes)
        
        # Decide which IR nodes should be emphasized as targets for this call.
        # For initialization / full generation we include all NL / hole / call nodes.
        # For regeneration after an edit, the caller can pass a smaller focus_nodes set.
        if focus_nodes:
            target_ir_nodes = focus_nodes
        else:
            target_ir_nodes = [n for n in nodes if n.type in ('nl_phrase', 'hole', 'function_call')]

        target_nodes_payload = [self._node_to_dict(n) for n in target_ir_nodes]
        
        # Single LLM call: generate full code or diff
        llm_output, success = self.llm_service.generate_code(
            annotated_semiformal=annotated_semiformal,
            existing_python=existing_python,
            target_nodes=target_nodes_payload if target_nodes_payload else None,
            trigger_type=trigger_type,
            previous_semiformal=previous_semiformal,
        )
        
        if not success:
            # Fallback: use direct reconstruction for Python nodes
            fallback_code = self._fallback_generation(nodes, context)
            fallback_mappings = self._create_simple_mappings(nodes, fallback_code)
            return fallback_code, fallback_mappings
        
        # Use postprocessor for diff application, AST analysis, and mapping
        mode = 'diff' if existing_python and existing_python.strip() else 'full'
        parsed_nodes = [self._node_to_dict(n) for n in nodes]
        
        post_result = self.postprocessor.process_generated_output(
            llm_output=llm_output,
            mode=mode,
            existing_code=existing_python if mode == 'diff' else "",
            parsed_nodes=parsed_nodes
        )
        
        final_code = post_result.get('code', existing_python if mode == 'diff' else llm_output)
        node_mapping = post_result.get('mapping', {})
        
        # Convert postprocessor mapping dict → List[Mapping] (Mapping dataclass)
        mappings: List[Mapping] = []
        code_lines = final_code.split('\n')
        
        for node in nodes:
            info = node_mapping.get(node.id)
            if not info or info.get('status') != 'mapped':
                continue
            
            primary_line = info.get('primary_line', 0)
            if 1 <= primary_line <= len(code_lines):
                snippet = code_lines[primary_line - 1].rstrip('\n')
            else:
                snippet = ""
            
            primary_ast_node = info.get('primary_node')
            
            mappings.append(Mapping(
                node_id=node.id,
                slices=[CodeSlice(
                    code=snippet,
                    line_start=primary_line,
                    line_end=primary_line,
                    ast_nodes=[primary_ast_node] if primary_ast_node is not None else []
                )],
                confidence=0.9,
                generation_method='postprocessed_anchor_mapping'
            ))
        
        return final_code, mappings

    def _annotate_semiformal_with_nodes(
        self,
        semiformal_code: str,
        nodes: List[IntentNode]
    ) -> str:
        """
        Create annotated semiformal text with anchor comments above each line.
        
        Converts parsed nodes into annotated text format with anchor comments
        that serve as semantic anchors for code generation.
        """
        return create_annotated_semiformal_text(nodes, semiformal_code)
    
    def _create_simple_mappings(
        self,
        nodes: List[IntentNode],
        generated_code: str
    ) -> List[Mapping]:
        """
        Create simple mappings from nodes to generated code.
        
        This is a simplified version - can be improved with better matching later.
        """
        mappings = []
        code_lines = generated_code.split('\n')
        
        for node in nodes:
            # Simple heuristic: map by line number
            sf_line = node.span[0]
            if sf_line < len(code_lines):
                code_line = code_lines[sf_line] if sf_line < len(code_lines) else ""
                mappings.append(Mapping(
                    node_id=node.id,
                    slices=[CodeSlice(
                        code=code_line,
                        line_start=sf_line + 1,
                        line_end=sf_line + 1,
                        ast_nodes=[]
                    )],
                    confidence=0.7,
                    generation_method='llm_generated'
                ))
        
        return mappings
    
    def _fallback_generation(
        self,
        nodes: List[IntentNode],
        context: str
    ) -> str:
        """
        Fallback generation when LLM is unavailable.
        Uses direct reconstruction for Python nodes.
        """
        lines_dict: Dict[int, List[IntentNode]] = {}
        for node in nodes:
            line_num = node.span[0]
            if line_num not in lines_dict:
                lines_dict[line_num] = []
            lines_dict[line_num].append(node)
        
        generated_lines = []
        for line_num in sorted(lines_dict.keys()):
            line_nodes = lines_dict[line_num]
            code = self._reconstruct_python(line_nodes)
            generated_lines.append(code)
        
        return '\n'.join(generated_lines)
    
    def _node_to_dict(self, node: IntentNode) -> Dict[str, Any]:
        """Convert IntentNode to dictionary"""
        return {
            'id': node.id,
            'type': node.type,
            'value': node.content,
            'line': node.span[0] + 1,
            'col': 0,
            'span': node.span,
            'metadata': node.metadata
        }

    def _analyze_undefined_functions(
        self,
        nodes: List[IntentNode],
        context: str,
        base_code: str
    ) -> List[FunctionSignature]:
        """Analyze nodes to find undefined function calls."""
        function_calls = [n for n in nodes if n.type == 'function_call']
        defined_functions = set()
        
        for node in nodes:
            if node.type == 'function_def':
                defined_functions.add(node.content)
        
        # Check in base_code
        try:
            tree = ast.parse(base_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    defined_functions.add(node.name)
        except:
            pass
        
        # Builtin functions
        builtins = {
            'print', 'len', 'range', 'enumerate', 'zip', 'map', 'filter',
            'open', 'input', 'int', 'str', 'float', 'list', 'dict', 'set',
            'sum', 'min', 'max', 'sorted', 'reversed',
            'read_csv', 'DataFrame', 'Series', 'array', 'zeros', 'ones',
            'plot', 'scatter', 'hist', 'show'
        }
        
        undefined = []
        for call_node in function_calls:
            func_name = call_node.content
            if func_name not in defined_functions and func_name not in builtins:
                sig = self._extract_signature_from_call(call_node, nodes)
                undefined.append(sig)
        
        return undefined

    def _extract_signature_from_call(
        self,
        call_node: IntentNode,
        all_nodes: List[IntentNode]
    ) -> FunctionSignature:
        """Extract function signature from a function call node"""
        arg_node_ids = call_node.metadata.get('arg_node_ids', [])
        kwarg_node_ids = call_node.metadata.get('kwarg_node_ids', {})
        
        positional_args = []
        for arg_id in arg_node_ids:
            arg_node = next((n for n in all_nodes if n.id == arg_id), None)
            if arg_node:
                positional_args.append(arg_node.content)
        
        keyword_args = {}
        for kwarg_name, kwarg_node_id in kwarg_node_ids.items():
            kwarg_node = next((n for n in all_nodes if n.id == kwarg_node_id), None)
            if kwarg_node:
                keyword_args[kwarg_name] = kwarg_node.content
        
        return FunctionSignature(
            name=call_node.content,
            positional_args=positional_args,
            keyword_args=keyword_args,
            call_node_id=call_node.id
        )

    def _infer_intent(self, signature: FunctionSignature, context: str) -> str:
        """Infer the intent of a function from its name and context"""
        name_parts = signature.name.replace('_', ' ')
        return f"Function to {name_parts}"

    def _reconstruct_python(self, nodes: List[IntentNode]) -> str:
        """Reconstruct Python code from nodes."""
        # If there's an expr_stmt node, return it
        for node in nodes:
            if node.type == 'expr_stmt':
                return node.metadata.get('full_statement', node.content)
            if node.type == 'python_stmt':
                return node.content
            if node.metadata.get('full_statement'):
                return node.metadata['full_statement']
            if node.metadata.get('full_code'):
                return node.metadata['full_code']

        # Build from components
        targets = [n for n in nodes if n.type == 'identifier' and n.metadata.get('role') == 'target']
        funcs = [n for n in nodes if n.type in ('function_call', 'function_def')]
        refs = [n for n in nodes if n.type == 'identifier' and n.metadata.get('role') == 'reference']
        literals = [n for n in nodes if n.type == 'literal']
        operators = [n for n in nodes if n.type == 'operator']

        if targets:
            lhs = ', '.join(t.content for t in targets)
            
            if funcs:
                func_name = funcs[0].content
                if funcs[0].metadata.get('full_call'):
                    rhs = funcs[0].metadata['full_call']
                else:
                    args = ', '.join(r.content for r in refs) if refs else ''
                    rhs = f"{func_name}({args})"
            elif operators:
                all_values = sorted(literals + refs, key=lambda n: n.span[0])
                parts = []
                for i, val in enumerate(all_values):
                    content = val.content
                    if val.type == 'literal' and val.metadata.get('literal_type') == 'str':
                        content = f'"{content}"'
                    parts.append(content)
                    if i < len(operators):
                        parts.append(operators[i].content)
                rhs = ' '.join(parts)
            elif literals:
                rhs = literals[0].content
                if literals[0].metadata.get('literal_type') == 'str':
                    rhs = f'"{rhs}"'
            elif refs:
                rhs = ', '.join(r.content for r in refs)
            else:
                rhs = 'None'
            
            return f"{lhs} = {rhs}"

        # Function definition
        func_defs = [n for n in nodes if n.type == 'function_def']
        if func_defs:
            func_node = func_defs[0]
            if 'full_code' in func_node.metadata:
                return func_node.metadata['full_code']
            params_nodes = [n for n in nodes if n.type == 'parameter']
            params = ', '.join(p.content for p in params_nodes)
            return f"def {func_node.content}({params}):\n    ..."

        # Function call
        if funcs:
            func = funcs[0]
            if func.metadata.get('full_call'):
                return func.metadata['full_call']
            args_parts = []
            arg_node_ids = func.metadata.get('arg_node_ids', [])
            for arg_node_id in arg_node_ids:
                arg_node = next((n for n in nodes if n.id == arg_node_id), None)
                if arg_node:
                    args_parts.append(arg_node.content)
            if not args_parts and refs:
                args_parts = [r.content for r in refs]
            args_str = ', '.join(args_parts)
            return f"{func.content}({args_str})"

        # Fallback
        parts = [n.content for n in nodes]
        return ' '.join(parts)