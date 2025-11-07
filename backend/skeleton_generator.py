"""
Skeleton code generator - creates Python structure without LLM.

This module generates Python "skeleton" code instantly by:
- Preserving already-generated code
- Copying complete Python nodes as-is
- Creating stubs for incomplete functions
- Creating placeholders for incomplete variables
- Rendering pseudocode as comments
- Updating signatures while preserving implementations

This provides immediate visual feedback without waiting for LLM generation,
and maintains generated code across spec updates.
"""

import ast
from typing import List, Optional, Set, Tuple
from ir import ProgramIR, IRNode, NodeType, NodeStatus, SourceLocation
from ast_operations import ASTMapper, generate_ast_path


class SkeletonGenerator:
    """
    Generates complete, executable Python programs from IR without LLM.
    
    Key principles:
    - Right side is ALWAYS a complete, runnable program
    - Generates stubs for undefined functions called in spec
    - Copies complete Python directly (e.g., print statements)
    - Spec is a projection/view of the complete code
    """
    
    def __init__(self):
        self.generated_stubs = set()  # Track which stubs we've generated
        self.mapper = ASTMapper()  # AST-level mapping
    
    def generate(self, ir: ProgramIR) -> str:
        """
        Generate complete, executable Python program from IR.
        
        Strategy:
        1. Generate stubs for all undefined functions (at top)
        2. Generate defined functions
        3. Generate statements (assignments, calls, etc.)
        
        This ensures right side is always a complete program.
        
        Args:
            ir: Program IR with parsed nodes
        
        Returns:
            Complete, executable Python code
        """
        self.generated_stubs = set()
        lines = []
        current_line = 1
        
        # Phase 1: Collect undefined function calls that need stubs
        undefined_funcs = {}  # name -> IRNode
        for node in ir.nodes.values():
            if node.node_type == NodeType.FUNCTION_CALL and node.metadata.get('needs_stub'):
                if node.name not in undefined_funcs:
                    undefined_funcs[node.name] = node
        
        # Generate stubs for undefined functions (at top of file)
        for func_name, node in sorted(undefined_funcs.items()):
            stub_code = self._generate_function_stub_from_call(node, ir)
            if stub_code:
                code_lines = stub_code.split('\n')
                lines.append(stub_code)
                lines.append("")  # Add spacing
                current_line += len(code_lines) + 1
                self.generated_stubs.add(func_name)
        
        # Phase 2: Generate code from spec nodes in order
        # Don't include FUNCTION_CALL nodes (they're handled as stubs at the top)
        sorted_nodes = sorted(
            [n for n in ir.nodes.values() if n.node_type != NodeType.FUNCTION_CALL],
            key=lambda n: n.spec_location.line if n.spec_location else float('inf')
        )
        
        prev_line = 0
        for node in sorted_nodes:
            # Skip nodes without location
            if not node.spec_location:
                continue
            
            # Add spacing between nodes
            if prev_line > 0 and node.spec_location.line - prev_line > 1:
                lines.append("")
                current_line += 1
            
            # Generate code based on node type and status
            code = self._generate_node_code(node)
            if code:
                # Update code location for bidirectional mapping
                code_lines = code.split('\n')
                node.code_location = SourceLocation(
                    line=current_line,
                    col=0,
                    end_line=current_line + len(code_lines) - 1,
                    end_col=len(code_lines[-1]) if code_lines else 0
                )
                
                lines.append(code)
                current_line += len(code_lines)
                prev_line = node.spec_location.line
        
        result = "\n".join(lines)
        
        # Build AST-level mapping
        self._build_ast_mapping(result, ir)
        
        return result
    
    def _build_ast_mapping(self, code: str, ir: ProgramIR) -> None:
        """
        Build AST-level mapping between spec nodes and generated code.
        
        This enables structural transformations without regeneration.
        """
        try:
            code_ast = ast.parse(code)
            
            # Map each code statement/definition to spec node
            for i, stmt in enumerate(code_ast.body):
                # Find which spec node this corresponds to
                spec_node = self._find_spec_node_for_statement(stmt, ir, i)
                if spec_node:
                    # Generate path to this statement
                    ast_path = f"body[{i}]"
                    spec_node.code_ast_path = ast_path
                    spec_node.code_ast = stmt
                    self.mapper.add_mapping(spec_node.id, ast_path)
        except Exception as e:
            # If parsing fails, just skip mapping
            print(f"Warning: Could not build AST mapping: {e}")
    
    def _find_spec_node_for_statement(self, stmt: ast.AST, ir: ProgramIR, index: int) -> Optional[IRNode]:
        """Find which spec node corresponds to this code statement."""
        # Match by type and name
        if isinstance(stmt, ast.FunctionDef):
            # Find function node by name
            for node in ir.nodes.values():
                if node.node_type == NodeType.FUNCTION_DEF and node.name == stmt.name:
                    return node
        
        elif isinstance(stmt, ast.Assign):
            # Find variable assignment by LHS
            if stmt.targets and isinstance(stmt.targets[0], ast.Name):
                var_name = stmt.targets[0].id
                for node in ir.nodes.values():
                    if node.node_type in (NodeType.VARIABLE_ASSIGN, NodeType.NL_EXPRESSION) and node.name == var_name:
                        return node
            elif stmt.targets and isinstance(stmt.targets[0], ast.Tuple):
                # Multiple assignment like x, y = ...
                # Use first variable as key
                if stmt.targets[0].elts and isinstance(stmt.targets[0].elts[0], ast.Name):
                    var_name = stmt.targets[0].elts[0].id
                    for node in ir.nodes.values():
                        if node.node_type in (NodeType.VARIABLE_ASSIGN, NodeType.NL_EXPRESSION) and node.name == var_name:
                            return node
        
        elif isinstance(stmt, ast.Expr):
            # Statement node
            for node in ir.nodes.values():
                if node.node_type == NodeType.STATEMENT and node.metadata.get('is_statement'):
                    # Match by line number or content
                    return node
        
        return None
    
    def _generate_node_code(self, node: IRNode) -> str:
        """
        Generate code for a single IR node.
        
        Strategy:
        - GENERATED/USER_EDITED: Use existing code_text (preserve generated code)
        - NEEDS_REGEN: Use updated code_text (signature was updated by IR merge)
        - SYNCED: Use spec_text as-is (already complete Python)
        - INCOMPLETE function: Create stub
        - INCOMPLETE variable: Create placeholder
        - NL_EXPRESSION: Create annotated placeholder
        - PSEUDOCODE: Render as comment
        """
        # First priority: preserve already-generated code
        # Use value comparison to avoid enum identity issues with different import paths
        if node.status.value in ('generated', 'user_edited', 'needs_regen'):
            if node.code_text:
                # Use existing generated/edited code
                return node.code_text
        
        # Second priority: use complete spec code
        if node.status.value == 'synced':
            # Already complete, use as-is
            return node.spec_text
        
        # Node is incomplete, generate appropriate placeholder
        if node.node_type == NodeType.FUNCTION_DEF:
            return self._create_function_stub(node)
        
        elif node.node_type == NodeType.VARIABLE_ASSIGN:
            # For variable assignments that reference incomplete functions,
            # still generate the assignment but with placeholder
            return self._create_variable_placeholder(node)
        
        elif node.node_type == NodeType.NL_EXPRESSION:
            # Natural language expression - create placeholder
            return self._create_variable_placeholder(node)
        
        elif node.node_type == NodeType.FUNCTION_CALL:
            # Undefined function call - create stub definition
            if node.metadata.get('needs_stub'):
                return self._create_function_stub(node)
            return ""
        
        elif node.node_type == NodeType.STATEMENT:
            # Complete Python statement - copy directly
            if node.status.value == 'synced':
                return node.spec_text
            # Incomplete statement
            return f"# TODO: {node.spec_text}"
        
        # Handle pseudocode (if we add this node type)
        if node.metadata.get('is_pseudocode'):
            return self._create_pseudocode_comment(node)
        
        # Default: comment it out
        return f"# TODO: {node.spec_text}"
    
    def _create_function_stub(self, node: IRNode) -> str:
        """
        Create a function stub for incomplete function.
        
        Extracts signature from AST or text and creates a stub with:
        - Proper signature (name and parameters)
        - Docstring indicating it's a stub
        - Ellipsis (...) body
        """
        # Try to extract from AST first
        if node.spec_ast and isinstance(node.spec_ast, ast.FunctionDef):
            func_def = node.spec_ast
            
            # Extract parameters
            params = []
            for arg in func_def.args.args:
                # Include type hints if present
                if arg.annotation:
                    try:
                        params.append(f"{arg.arg}: {ast.unparse(arg.annotation)}")
                    except:
                        params.append(arg.arg)
                else:
                    params.append(arg.arg)
            
            params_str = ', '.join(params)
            
            # Extract return type hint if present
            return_hint = ""
            if func_def.returns:
                try:
                    return_hint = f" -> {ast.unparse(func_def.returns)}"
                except:
                    pass
            
            # Check if there's a docstring in original
            docstring = ast.get_docstring(func_def)
            if docstring:
                doc_line = f'    """{docstring}"""'
            else:
                doc_line = f'    """TODO: Implement {node.name}"""'
            
            return f"""def {node.name}({params_str}){return_hint}:
{doc_line}
    ..."""
        
        # Fallback: parse text manually
        import re
        func_match = re.match(r'def\s+(\w+)\s*\((.*?)\)\s*(?:->.*?)?:', node.spec_text)
        if func_match:
            func_name = func_match.group(1)
            params = func_match.group(2)
            
            return f"""def {func_name}({params}):
    \"\"\"TODO: Implement {func_name}\"\"\"
    ..."""
        
        # Last resort: simple stub
        return f"""def {node.name}():
    \"\"\"TODO: Implement {node.name}\"\"\"
    ..."""
    
    def _generate_function_stub_from_call(self, node: IRNode, ir: ProgramIR) -> str:
        """
        Generate a function stub based on how it's called in the spec.
        
        This analyzes all calls to the function to infer the signature.
        
        Args:
            node: FUNCTION_CALL node
            ir: Program IR to find all calls to this function
        
        Returns:
            Function stub code
        """
        func_name = node.name
        
        # Find all calls to this function in the spec to infer parameters
        # For now, create a simple stub with *args, **kwargs
        # TODO: Infer actual parameters from call sites
        
        return f"""def {func_name}(*args, **kwargs):
    \"\"\"TODO: Implement {func_name}\"\"\"
    raise NotImplementedError("{func_name} needs implementation")"""
    
    def _create_variable_placeholder(self, node: IRNode) -> str:
        """
        Create code for variable assignment.
        
        Strategy:
        - If it's complete Python (calls to defined/builtin functions), copy as-is
        - If it's natural language, create commented placeholder
        - If it calls undefined functions, keep the call (stub will be generated)
        """
        # If the spec text is complete Python syntax, use it directly
        # This handles cases like: result = process_data(raw_input)
        # where process_data will have a stub generated
        if node.node_type == NodeType.VARIABLE_ASSIGN and not node.metadata.get('is_nl'):
            # It's syntactically valid Python, use it
            return node.spec_text
        
        # It's natural language or has other issues
        nl_desc = node.metadata.get('rhs', '') or node.metadata.get('nl_description', '')
        
        if nl_desc and nl_desc != '...':
            # Natural language - create placeholder with comment
            nl_desc = nl_desc.strip()
            return f"{node.name} = ...  # {nl_desc}"
        else:
            return f"{node.name} = ...  # TODO: Define {node.name}"
    
    def _create_pseudocode_comment(self, node: IRNode) -> str:
        """
        Render pseudocode as commented natural language.
        
        Preserves indentation and multi-line structure.
        """
        lines = node.spec_text.split('\n')
        
        commented = []
        for line in lines:
            if line.strip():
                commented.append(f"# PSEUDOCODE: {line}")
            else:
                commented.append("")
        
        return '\n'.join(commented)


def generate_skeleton(ir: ProgramIR) -> str:
    """
    Convenience function to generate complete, executable Python from IR.
    
    Args:
        ir: Program IR
    
    Returns:
        Complete, executable Python code
    """
    generator = SkeletonGenerator()
    return generator.generate(ir)

