"""
AST-based parser for building the IR from semiformal Python specifications.

This parser uses Python's ast module to properly analyze:
- Dependencies between nodes
- Data flow
- Type information
- Scope and context

It builds a complete IR with dependency graph for robust bidirectional sync.
Uses AST-based signature extraction and change detection for proper
incremental updates.
"""

import ast
import re
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass

from ir import (
    ProgramIR, IRNode, NodeType, NodeStatus, SourceLocation,
    create_node_id
)


def extract_function_signature(func_node: ast.FunctionDef) -> str:
    """
    Extract normalized function signature from AST.
    
    Returns a canonical representation for comparison:
    "func_name(arg1, arg2: type2, *args, kwarg1=default, **kwargs) -> return_type"
    """
    parts = [func_node.name, "("]
    
    args = func_node.args
    arg_strs = []
    
    # Regular positional/keyword arguments
    num_defaults = len(args.defaults)
    num_args = len(args.args)
    
    for i, arg in enumerate(args.args):
        arg_str = arg.arg
        if arg.annotation:
            try:
                arg_str += f": {ast.unparse(arg.annotation)}"
            except:
                pass
        
        # Check if this arg has a default (defaults are right-aligned)
        default_idx = i - (num_args - num_defaults)
        if default_idx >= 0 and default_idx < num_defaults:
            try:
                arg_str += f"={ast.unparse(args.defaults[default_idx])}"
            except:
                pass
        
        arg_strs.append(arg_str)
    
    # *args
    if args.vararg:
        vararg_str = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            try:
                vararg_str += f": {ast.unparse(args.vararg.annotation)}"
            except:
                pass
        arg_strs.append(vararg_str)
    
    # Keyword-only arguments
    for i, arg in enumerate(args.kwonlyargs):
        arg_str = arg.arg
        if arg.annotation:
            try:
                arg_str += f": {ast.unparse(arg.annotation)}"
            except:
                pass
        # Add default if present
        if i < len(args.kw_defaults) and args.kw_defaults[i]:
            try:
                arg_str += f"={ast.unparse(args.kw_defaults[i])}"
            except:
                pass
        arg_strs.append(arg_str)
    
    # **kwargs
    if args.kwarg:
        kwarg_str = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            try:
                kwarg_str += f": {ast.unparse(args.kwarg.annotation)}"
            except:
                pass
        arg_strs.append(kwarg_str)
    
    parts.append(", ".join(arg_strs))
    parts.append(")")
    
    # Return type
    if func_node.returns:
        try:
            parts.append(f" -> {ast.unparse(func_node.returns)}")
        except:
            pass
    
    return "".join(parts)


def extract_variable_signature(var_name: str, assign_node: ast.Assign) -> str:
    """
    Extract normalized variable assignment signature.
    
    For variables, the signature is just the variable name and type hint if present.
    """
    # Check if there's a type annotation
    if hasattr(assign_node, 'annotation') and assign_node.annotation:
        try:
            type_str = ast.unparse(assign_node.annotation)
            return f"{var_name}: {type_str}"
        except:
            pass
    
    return var_name


def extract_call_signature(call_node: ast.Call) -> str:
    """
    Extract function call signature for tracking.
    
    Returns: "func_name(arg_types...)"
    """
    func_name = ""
    if isinstance(call_node.func, ast.Name):
        func_name = call_node.func.id
    elif isinstance(call_node.func, ast.Attribute):
        try:
            func_name = ast.unparse(call_node.func)
        except:
            func_name = call_node.func.attr
    
    # Count arguments
    num_args = len(call_node.args)
    num_kwargs = len(call_node.keywords)
    
    return f"{func_name}({num_args} args, {num_kwargs} kwargs)"


class DependencyAnalyzer(ast.NodeVisitor):
    """
    Analyzes dependencies in AST by tracking:
    - Variable definitions and uses
    - Function definitions and calls
    - Data flow between statements
    """
    
    def __init__(self):
        self.defined_names: Set[str] = set()  # Names defined in current scope
        self.used_names: Set[str] = set()      # Names used before definition
        self.function_defs: Dict[str, ast.FunctionDef] = {}
        self.function_calls: Dict[str, List[ast.Call]] = {}
        self.variable_assigns: Dict[str, ast.Assign] = {}
        self.current_function: Optional[str] = None
        
        # Track dependencies: name -> set of names it depends on
        self.dependencies: Dict[str, Set[str]] = {}
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition."""
        self.function_defs[node.name] = node
        self.defined_names.add(node.name)
        
        # Enter function scope
        prev_function = self.current_function
        self.current_function = node.name
        self.dependencies[node.name] = set()
        
        # Visit function body
        prev_defined = self.defined_names.copy()
        
        # Add parameters to defined names
        for arg in node.args.args:
            self.defined_names.add(arg.arg)
        
        for stmt in node.body:
            self.visit(stmt)
        
        # Restore scope
        self.current_function = prev_function
        self.defined_names = prev_defined
        
        self.generic_visit(node)
    
    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignment statement."""
        # First, visit RHS to track dependencies
        self.visit(node.value)
        
        # Then mark LHS as defined
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                self.variable_assigns[var_name] = node
                
                # Track dependencies for this assignment
                if self.current_function:
                    deps = self._extract_names_from_expr(node.value)
                    if var_name not in self.dependencies:
                        self.dependencies[var_name] = set()
                    self.dependencies[var_name].update(deps)
                
                self.defined_names.add(var_name)
    
    def visit_Call(self, node: ast.Call) -> None:
        """Visit function call."""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            
            if func_name not in self.function_calls:
                self.function_calls[func_name] = []
            self.function_calls[func_name].append(node)
            
            # Track dependencies
            if self.current_function and func_name not in self.defined_names:
                if self.current_function not in self.dependencies:
                    self.dependencies[self.current_function] = set()
                self.dependencies[self.current_function].add(func_name)
        
        self.generic_visit(node)
    
    def visit_Name(self, node: ast.Name) -> None:
        """Visit name reference."""
        if isinstance(node.ctx, ast.Load):
            # Name is being used
            if node.id not in self.defined_names:
                self.used_names.add(node.id)
                
                # Track dependency in current context
                if self.current_function:
                    if self.current_function not in self.dependencies:
                        self.dependencies[self.current_function] = set()
                    self.dependencies[self.current_function].add(node.id)
        
        self.generic_visit(node)
    
    def _extract_names_from_expr(self, node: ast.AST) -> Set[str]:
        """Extract all name references from an expression."""
        names = set()
        
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                names.add(child.id)
        
        return names


class SemiformalParser:
    """
    Main parser that builds IR from semiformal Python code.
    
    Handles:
    - Complete Python code
    - Incomplete code (... stubs)
    - Natural language expressions
    - Mixed semiformal/formal code
    """
    
    def __init__(self):
        self.ir = ProgramIR()
        self.analyzer = DependencyAnalyzer()
        self.line_to_node: Dict[int, str] = {}  # Maps line number to node ID
        self.spec_source: str = ""  # Store spec source for reference checking
    
    def parse(self, spec_code: str) -> ProgramIR:
        """
        Parse semiformal code and build IR.
        
        Args:
            spec_code: Semiformal Python specification
        
        Returns:
            Complete ProgramIR with dependency graph
        """
        self.ir = ProgramIR()
        self.ir.spec_source = spec_code
        self.analyzer = DependencyAnalyzer()
        self.spec_source = spec_code  # Store for reference checking
        
        # Try to parse as much as possible
        try:
            tree = ast.parse(spec_code)
            self._build_ir_from_ast(tree, spec_code)
        except SyntaxError:
            # Code has syntax errors, try line-by-line parsing
            self._parse_incomplete_code(spec_code)
        
        # Build dependency graph
        self._build_dependency_graph()
        
        return self.ir
    
    def _build_ir_from_ast(self, tree: ast.AST, source: str) -> None:
        """Build IR from valid AST."""
        # Run dependency analysis
        self.analyzer.visit(tree)
        
        # Track statement-level nodes (not just definitions and assignments)
        # This includes standalone function calls like print()
        self.statement_nodes = []
        
        lines = source.split('\n')
        
        # Create nodes for function definitions
        for func_name, func_node in self.analyzer.function_defs.items():
            node_id = create_node_id(NodeType.FUNCTION_DEF, func_name, func_node.lineno)
            
            # Extract function text
            func_text = ast.get_source_segment(source, func_node)
            if not func_text:
                # Fallback: reconstruct from lines
                func_text = self._extract_node_text(func_node, lines)
            
            # Extract signature using AST
            spec_signature = extract_function_signature(func_node)
            
            # Determine status - check for ellipsis, NL, or undefined/incomplete references
            has_incomplete_refs = self._has_undefined_or_incomplete_references(func_node, func_name)
            status = self._determine_status(func_text)
            
            # Override status if has undefined/incomplete references
            if has_incomplete_refs and status == NodeStatus.SYNCED:
                status = NodeStatus.INCOMPLETE
            
            ir_node = IRNode(
                id=node_id,
                node_type=NodeType.FUNCTION_DEF,
                name=func_name,
                status=status,
                spec_location=SourceLocation(
                    line=func_node.lineno,
                    col=func_node.col_offset,
                    end_line=getattr(func_node, 'end_lineno', None),
                    end_col=getattr(func_node, 'end_col_offset', None)
                ),
                spec_ast=func_node,
                spec_text=func_text,
                spec_signature=spec_signature
            )
            
            # Compute hash for change detection
            ir_node.spec_hash = ir_node.compute_spec_hash()
            
            self.ir.add_node(ir_node)
            self.line_to_node[func_node.lineno] = node_id
        
        # Create nodes for variable assignments
        for var_name, assign_node in self.analyzer.variable_assigns.items():
            node_id = create_node_id(NodeType.VARIABLE_ASSIGN, var_name, assign_node.lineno)
            
            # Extract assignment text
            assign_text = ast.get_source_segment(source, assign_node)
            if not assign_text:
                assign_text = self._extract_node_text(assign_node, lines)
            
            # Extract signature
            spec_signature = extract_variable_signature(var_name, assign_node)
            
            # Check if RHS is natural language or references undefined/incomplete functions
            is_nl = self._is_nl_expression(assign_text)
            has_incomplete_refs = self._has_undefined_or_incomplete_references(assign_node, var_name)
            node_type = NodeType.NL_EXPRESSION if is_nl else NodeType.VARIABLE_ASSIGN
            
            status = NodeStatus.INCOMPLETE if (is_nl or "..." in assign_text or has_incomplete_refs) else NodeStatus.SYNCED
            
            ir_node = IRNode(
                id=node_id,
                node_type=node_type,
                name=var_name,
                status=status,
                spec_location=SourceLocation(
                    line=assign_node.lineno,
                    col=assign_node.col_offset,
                    end_line=getattr(assign_node, 'end_lineno', None),
                    end_col=getattr(assign_node, 'end_col_offset', None)
                ),
                spec_ast=assign_node,
                spec_text=assign_text,
                spec_signature=spec_signature,
                metadata={'is_nl': is_nl}
            )
            
            # Compute hash
            ir_node.spec_hash = ir_node.compute_spec_hash()
            
            self.ir.add_node(ir_node)
            self.line_to_node[assign_node.lineno] = node_id
        
        # Create nodes for function calls (that aren't defined)
        # Get builtins properly
        import builtins
        builtin_names = set(dir(builtins))
        
        for func_name, call_nodes in self.analyzer.function_calls.items():
            # Check if function is undefined (not a builtin and not defined in code)
            is_builtin = func_name in builtin_names
            is_defined = func_name in self.analyzer.function_defs
            
            if not is_builtin and not is_defined:
                # Undefined function call - needs stub
                for i, call_node in enumerate(call_nodes):
                    node_id = create_node_id(NodeType.FUNCTION_CALL, func_name, call_node.lineno)
                    
                    # Don't create duplicate nodes
                    if node_id in self.ir.nodes:
                        continue
                    
                    call_text = ast.get_source_segment(source, call_node) or ""
                    
                    # Extract call signature
                    call_signature = extract_call_signature(call_node)
                    
                    ir_node = IRNode(
                        id=node_id,
                        node_type=NodeType.FUNCTION_CALL,
                        name=func_name,
                        status=NodeStatus.INCOMPLETE,
                        spec_location=SourceLocation(
                            line=call_node.lineno,
                            col=call_node.col_offset
                        ),
                        spec_ast=call_node,
                        spec_text=call_text,
                        spec_signature=call_signature,
                        metadata={'needs_stub': True}
                    )
                    
                    # Compute hash
                    ir_node.spec_hash = ir_node.compute_spec_hash()
                    
                    self.ir.add_node(ir_node)
        
        # Create nodes for standalone statements (like print calls)
        # These are expression statements that aren't assignments or definitions
        for stmt in tree.body:
            if isinstance(stmt, ast.Expr):
                # This is a standalone expression statement
                stmt_text = ast.get_source_segment(source, stmt) or ""
                
                # Create a STATEMENT node for complete Python statements
                node_id = create_node_id(NodeType.STATEMENT, f"stmt_{stmt.lineno}", stmt.lineno)
                
                ir_node = IRNode(
                    id=node_id,
                    node_type=NodeType.STATEMENT,
                    name=f"statement_{stmt.lineno}",
                    status=NodeStatus.SYNCED,  # It's complete Python
                    spec_location=SourceLocation(
                        line=stmt.lineno,
                        col=stmt.col_offset,
                        end_line=getattr(stmt, 'end_lineno', None),
                        end_col=getattr(stmt, 'end_col_offset', None)
                    ),
                    spec_ast=stmt,
                    spec_text=stmt_text,
                    spec_signature=stmt_text[:50],  # First 50 chars as signature
                    metadata={'is_statement': True}
                )
                
                ir_node.spec_hash = ir_node.compute_spec_hash()
                self.ir.add_node(ir_node)
                self.line_to_node[stmt.lineno] = node_id
    
    def _parse_incomplete_code(self, source: str) -> None:
        """
        Parse code that has syntax errors line by line.
        
        This handles incomplete code with ... stubs or NL expressions.
        """
        lines = source.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if not stripped or stripped.startswith('#'):
                continue
            
            # Check for pseudocode first
            if self._is_pseudocode(stripped):
                node_id = create_node_id(NodeType.PSEUDOCODE, f"pseudo_{line_num}", line_num)
                ir_node = IRNode(
                    id=node_id,
                    node_type=NodeType.PSEUDOCODE,
                    name=f"pseudocode_{line_num}",
                    status=NodeStatus.INCOMPLETE,
                    spec_location=SourceLocation(line=line_num, col=0),
                    spec_text=line,
                    spec_signature=f"pseudo_{line_num}",
                    metadata={'is_pseudocode': True}
                )
                ir_node.spec_hash = ir_node.compute_spec_hash()
                self.ir.add_node(ir_node)
                self.line_to_node[line_num] = node_id
                continue
            
            # Try to identify function definitions
            func_match = re.match(r'def\s+(\w+)\s*\((.*?)\):', stripped)
            if func_match:
                func_name = func_match.group(1)
                params = func_match.group(2)
                
                node_id = create_node_id(NodeType.FUNCTION_DEF, func_name, line_num)
                
                # Check if next line has ...
                has_ellipsis = False
                if line_num < len(lines) and '...' in lines[line_num]:
                    has_ellipsis = True
                
                status = NodeStatus.INCOMPLETE if has_ellipsis else NodeStatus.SYNCED
                
                # Build basic signature from regex match
                spec_signature = f"{func_name}({params})"
                
                ir_node = IRNode(
                    id=node_id,
                    node_type=NodeType.FUNCTION_DEF,
                    name=func_name,
                    status=status,
                    spec_location=SourceLocation(line=line_num, col=0),
                    spec_text=line,
                    spec_signature=spec_signature,
                    metadata={'params': params, 'has_ellipsis': has_ellipsis}
                )
                
                ir_node.spec_hash = ir_node.compute_spec_hash()
                self.ir.add_node(ir_node)
                self.line_to_node[line_num] = node_id
                continue
            
            # Try to identify variable assignments (including multiple LHS like x,y = ...)
            assign_match = re.match(r'([\w\s,]+)\s*=\s*(.+)', stripped)
            if assign_match:
                lhs = assign_match.group(1).strip()
                rhs = assign_match.group(2).strip()
                
                # Extract variable names from LHS
                var_names = [v.strip() for v in lhs.split(',')]
                var_name = var_names[0]  # Use first variable as the node name
                
                node_id = create_node_id(NodeType.VARIABLE_ASSIGN, var_name, line_num)
                
                is_nl = self._is_nl_expression(rhs)
                has_ellipsis = '...' in rhs
                
                # Check if RHS references undefined/incomplete functions
                has_undefined_func = self._check_rhs_for_undefined_funcs(rhs)
                
                # Extract function calls from RHS for stub generation
                self._extract_function_calls_from_text(rhs, line_num)
                
                node_type = NodeType.NL_EXPRESSION if is_nl else NodeType.VARIABLE_ASSIGN
                status = NodeStatus.INCOMPLETE if (is_nl or has_ellipsis or has_undefined_func) else NodeStatus.SYNCED
                
                ir_node = IRNode(
                    id=node_id,
                    node_type=node_type,
                    name=var_name,
                    status=status,
                    spec_location=SourceLocation(line=line_num, col=0),
                    spec_text=line,
                    spec_signature=var_name,  # Simple signature for variables
                    metadata={'rhs': rhs, 'is_nl': is_nl, 'lhs': var_names}
                )
                
                ir_node.spec_hash = ir_node.compute_spec_hash()
                self.ir.add_node(ir_node)
                self.line_to_node[line_num] = node_id
                continue
            
            # Check for function calls
            call_match = re.search(r'(\w+)\s*\(', stripped)
            if call_match:
                func_name = call_match.group(1)
                
                # Get builtins properly
                import builtins
                builtin_names = set(dir(builtins))
                
                # Only create node if function is not defined and not builtin
                is_defined = func_name in [n.name for n in self.ir.nodes.values() if n.node_type == NodeType.FUNCTION_DEF]
                is_builtin = func_name in builtin_names
                
                if not is_defined and not is_builtin:
                    # Undefined function - create FUNCTION_CALL node for stub generation
                    node_id = create_node_id(NodeType.FUNCTION_CALL, func_name, line_num)
                    
                    # Simple signature for call from text
                    call_signature = f"{func_name}(...)"
                    
                    ir_node = IRNode(
                        id=node_id,
                        node_type=NodeType.FUNCTION_CALL,
                        name=func_name,
                        status=NodeStatus.INCOMPLETE,
                        spec_location=SourceLocation(line=line_num, col=call_match.start()),
                        spec_text=stripped,
                        spec_signature=call_signature,
                        metadata={'needs_stub': True}
                    )
                    
                    ir_node.spec_hash = ir_node.compute_spec_hash()
                    self.ir.add_node(ir_node)
                else:
                    # Complete Python statement (builtin call or defined function)
                    # Create STATEMENT node so it appears in skeleton
                    node_id = create_node_id(NodeType.STATEMENT, f"stmt_{line_num}", line_num)
                    
                    ir_node = IRNode(
                        id=node_id,
                        node_type=NodeType.STATEMENT,
                        name=f"statement_{line_num}",
                        status=NodeStatus.SYNCED,
                        spec_location=SourceLocation(line=line_num, col=0),
                        spec_text=stripped,
                        spec_signature=stripped[:50],
                        metadata={'is_statement': True}
                    )
                    
                    ir_node.spec_hash = ir_node.compute_spec_hash()
                    self.ir.add_node(ir_node)
    
    def _build_dependency_graph(self) -> None:
        """Build dependency relationships between nodes."""
        # Use analyzer's dependency information
        for name, deps in self.analyzer.dependencies.items():
            # Find node for this name
            node_id = None
            for nid, node in self.ir.nodes.items():
                if node.name == name:
                    node_id = nid
                    break
            
            if not node_id:
                continue
            
            # Add dependencies
            for dep_name in deps:
                # Find dependency node
                dep_node_id = None
                for nid, node in self.ir.nodes.items():
                    if node.name == dep_name:
                        dep_node_id = nid
                        break
                
                if dep_node_id:
                    self.ir.add_dependency(node_id, dep_node_id)
    
    def _determine_status(self, text: str) -> NodeStatus:
        """Determine status of a code element."""
        if "..." in text:
            return NodeStatus.INCOMPLETE
        elif self._is_nl_expression(text):
            return NodeStatus.INCOMPLETE
        else:
            return NodeStatus.SYNCED
    
    def _extract_function_calls_from_text(self, text: str, line_num: int) -> None:
        """
        Extract function calls from text and create FUNCTION_CALL nodes for undefined ones.
        
        This is used to generate stubs for functions called but not defined.
        
        Args:
            text: Text to extract function calls from (e.g., RHS of assignment)
            line_num: Line number for location tracking
        """
        # Try to parse as expression to get function calls
        try:
            expr_ast = ast.parse(text, mode='eval')
            
            # Get builtins
            import builtins
            builtin_names = set(dir(builtins))
            
            # Walk the AST to find function calls
            for node in ast.walk(expr_ast):
                if isinstance(node, ast.Call):
                    func_name = None
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    
                    if func_name:
                        # Check if undefined
                        is_builtin = func_name in builtin_names
                        is_defined = func_name in self.analyzer.function_defs
                        
                        if not is_builtin and not is_defined:
                            # Create FUNCTION_CALL node for stub generation
                            node_id = create_node_id(NodeType.FUNCTION_CALL, func_name, line_num)
                            
                            # Don't create duplicate
                            if node_id not in self.ir.nodes:
                                ir_node = IRNode(
                                    id=node_id,
                                    node_type=NodeType.FUNCTION_CALL,
                                    name=func_name,
                                    status=NodeStatus.INCOMPLETE,
                                    spec_location=SourceLocation(line=line_num, col=0),
                                    spec_text=f"{func_name}(...)",
                                    spec_signature=f"{func_name}(...)",
                                    metadata={'needs_stub': True}
                                )
                                
                                ir_node.spec_hash = ir_node.compute_spec_hash()
                                self.ir.add_node(ir_node)
        except:
            # Can't parse, skip
            pass
    
    def _check_rhs_for_undefined_funcs(self, rhs: str) -> bool:
        """
        Check if RHS text contains calls to undefined/incomplete functions.
        
        Used in line-by-line parsing where we don't have AST.
        
        Args:
            rhs: Right-hand side of assignment as text
        
        Returns:
            True if RHS contains undefined/incomplete function calls
        """
        # Try to parse RHS as expression
        try:
            expr_ast = ast.parse(rhs, mode='eval')
            # Use the AST-based checker
            return self._has_undefined_or_incomplete_references(expr_ast, None)
        except:
            # Can't parse, assume it's incomplete
            return False
    
    def _has_undefined_or_incomplete_references(self, node: ast.AST, exclude_name: Optional[str] = None) -> bool:
        """
        Check if a node references undefined or incomplete functions/variables.
        
        This is key for bidirectional programming: if a node calls an incomplete
        function, it should also be marked as incomplete.
        
        Args:
            node: AST node to check
            exclude_name: Name to exclude from check (e.g., the variable being assigned)
        
        Returns:
            True if the node references undefined or incomplete names
        """
        # Get Python builtins
        import builtins
        builtin_names = set(dir(builtins))
        
        # Check for function calls to undefined or incomplete functions
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = None
                if isinstance(child.func, ast.Name):
                    func_name = child.func.id
                
                if func_name:
                    # Check if this function is a builtin (those are always complete)
                    if func_name in builtin_names:
                        continue
                    
                    # Check if function is defined in the code
                    if func_name in self.analyzer.function_defs:
                        # Function is defined, but check if it's incomplete (has ...)
                        func_node = self.analyzer.function_defs[func_name]
                        func_text = ast.get_source_segment(self.spec_source, func_node) or ""
                        if "..." in func_text:
                            # Function is incomplete!
                            return True
                    else:
                        # Function is not defined at all
                        return True
            
            # Check for variable references to undefined variables
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                var_name = child.id
                
                # Skip the variable being assigned
                if var_name == exclude_name:
                    continue
                
                # Check if it's defined
                is_builtin = var_name in builtin_names
                is_defined = var_name in self.analyzer.defined_names
                is_function_def = var_name in self.analyzer.function_defs
                
                # For variables, be lenient - forward references are OK
                # We mainly care about function calls
                pass
        
        return False
    
    def _is_nl_expression(self, text: str) -> bool:
        """
        Check if text contains natural language expression.
        
        Strategy:
        1. First try to parse as Python - if it parses, it's NOT NL
        2. Check for common NL patterns (multi-word phrases without Python syntax)
        3. Distinguish between undefined Python identifiers and true NL
        """
        text_stripped = text.strip()
        
        # Empty or ellipsis is not NL
        if not text_stripped or text_stripped == '...':
            return False
        
        # Try to parse as Python expression first
        try:
            ast.parse(text_stripped, mode='eval')
            # It's valid Python syntax, so NOT natural language
            # Even if it references undefined names, it's still Python
            return False
        except SyntaxError:
            pass
        
        # Can't parse as Python, check if it looks like natural language
        # Remove strings and comments for analysis
        cleaned = re.sub(r'["\'].*?["\']', '', text_stripped)
        cleaned = re.sub(r'#.*$', '', cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()
        
        if not cleaned:
            return False
        
        # Natural language indicators:
        # - Multiple words separated by spaces
        # - Contains common NL words (the, a, an, to, from, etc.)
        # - No Python operators or valid syntax
        
        words = cleaned.split()
        
        # Single word is not NL (it's likely a variable name)
        if len(words) < 2:
            return False
        
        # Check for natural language keywords
        nl_keywords = {
            'the', 'a', 'an', 'and', 'or', 'of', 'in', 'to', 'from', 'for',
            'with', 'by', 'at', 'into', 'using', 'where', 'when', 'that',
            'each', 'all', 'some', 'every', 'split', 'into', 'sets'
        }
        
        words_lower = [w.lower() for w in words]
        has_nl_keyword = any(w in nl_keywords for w in words_lower)
        
        # If it has NL keywords and multiple words, likely NL
        if has_nl_keyword and len(words) >= 3:
            return True
        
        # Check if it looks like a sentence (multiple words, no valid Python syntax)
        # and doesn't have Python-specific patterns
        has_python_patterns = bool(re.search(r'[\(\)\[\]\{\}=<>!]|==|!=|<=|>=|\+=|-=', cleaned))
        
        if len(words) >= 4 and not has_python_patterns:
            return True
        
        return False
    
    def _extract_node_text(self, node: ast.AST, lines: List[str]) -> str:
        """Extract source text for an AST node."""
        start_line = node.lineno - 1
        end_line = getattr(node, 'end_lineno', node.lineno) - 1
        
        if start_line == end_line:
            return lines[start_line]
        else:
            return '\n'.join(lines[start_line:end_line + 1])
    
    def _is_pseudocode(self, line: str) -> bool:
        """
        Detect if a line is pseudocode (not valid Python).
        
        Uses heuristics to identify natural language patterns
        that indicate pseudocode rather than incomplete Python.
        """
        line_lower = line.lower().strip()
        
        # Pseudocode keywords
        pseudocode_keywords = [
            'for each', 'for every', 'apply', 'using',
            'where', 'when', 'given', 'then',
            'calculate', 'compute', 'find all', 'determine',
            'select', 'filter', 'from', 'into'
        ]
        
        # Check for pseudocode keyword patterns
        if any(kw in line_lower for kw in pseudocode_keywords):
            # Make sure it's not just a variable name containing these words
            # e.g., "for_each_item = ..." should not be pseudocode
            if not ('=' in line and line.index('=') < line.lower().index(next(kw for kw in pseudocode_keywords if kw in line_lower))):
                return True
        
        # Check for natural language patterns:
        # - Multiple words with spaces
        # - No Python operators (except maybe :)
        # - Not a string literal
        # - Not a comment
        words = line_lower.split()
        if len(words) > 5:
            has_python_syntax = any(op in line for op in ['(', ')', '[', ']', '{', '}', '+', '-', '*', '/', '==', '!='])
            is_assignment = '=' in line and not any(op in line for op in ['==', '!=', '<=', '>='])
            
            # If it has many words, no Python syntax, and isn't an assignment, likely pseudocode
            if not has_python_syntax and not is_assignment:
                return True
        
        return False


def parse_semiformal(spec_code: str) -> ProgramIR:
    """
    Convenience function to parse semiformal code.
    
    Args:
        spec_code: Semiformal Python specification
    
    Returns:
        ProgramIR with complete dependency graph
    """
    parser = SemiformalParser()
    return parser.parse(spec_code)

