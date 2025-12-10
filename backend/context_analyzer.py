"""
Context Analyzer for Iterative Code Generation

Analyzes semiformal code changes to extract contextual information that helps
generate more accurate and context-aware function implementations.

Key features:
- Detects parameter additions/changes in function calls
- Infers data types and structures from literal arguments
- Tracks variable assignments and their data context
- Identifies data source changes (e.g., different CSV files)
"""

import ast
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from parser import IntentNode


@dataclass
class DataContext:
    """Represents inferred data context from code analysis"""
    source_file: Optional[str] = None  # e.g., 'titanic.csv', 'iris.csv'
    inferred_schema: Dict[str, str] = field(default_factory=dict)  # column_name -> type
    variable_name: Optional[str] = None
    context_hints: List[str] = field(default_factory=list)  # Free-form context hints


@dataclass
class FunctionCallContext:
    """Context information for a function call"""
    function_name: str
    positional_args: List[str] = field(default_factory=list)
    keyword_args: Dict[str, str] = field(default_factory=dict)
    call_line: int = 0
    assigned_to: Optional[str] = None  # Variable this is assigned to
    data_context: Optional[DataContext] = None
    
    
@dataclass
class ChangeContext:
    """Represents the context of a code change"""
    change_type: str  # 'new_call', 'param_added', 'param_changed', 'data_source_changed'
    affected_functions: List[str] = field(default_factory=list)
    new_parameters: Dict[str, Any] = field(default_factory=dict)
    data_contexts: Dict[str, DataContext] = field(default_factory=dict)  # var_name -> context
    previous_code: Optional[str] = None
    current_code: Optional[str] = None


class ContextAnalyzer:
    """
    Analyzes code changes to extract contextual information for intelligent code generation.
    
    This analyzer helps the system understand:
    1. What changed between iterations (new params, different data source, etc.)
    2. What context to use for generating function bodies
    3. What existing functions need to be updated vs. created fresh
    """
    
    def analyze_change(
        self,
        current_code: str,
        previous_code: Optional[str] = None,
        nodes: Optional[List[IntentNode]] = None
    ) -> ChangeContext:
        """
        Analyze what changed between previous and current code.
        
        Args:
            current_code: Current semiformal code
            previous_code: Previous semiformal code (if available)
            nodes: Parsed intent nodes for current code
            
        Returns:
            ChangeContext with detected changes and inferred context
        """
        context = ChangeContext(
            change_type='unknown',
            current_code=current_code,
            previous_code=previous_code
        )
        
        # Extract function calls from current code
        current_calls = self._extract_function_calls(current_code)
        
        # If we have previous code, detect what changed
        if previous_code:
            previous_calls = self._extract_function_calls(previous_code)
            context = self._detect_changes(previous_calls, current_calls, context)
        else:
            # No previous code - all calls are new
            context.change_type = 'initial'
            context.affected_functions = [c.function_name for c in current_calls]
        
        # Analyze data context for all function calls
        for call in current_calls:
            if call.assigned_to:
                data_ctx = self._infer_data_context(call, current_code)
                if data_ctx:
                    context.data_contexts[call.assigned_to] = data_ctx
        
        return context
    
    def _extract_function_calls(self, code: str) -> List[FunctionCallContext]:
        """Extract all function calls from code"""
        calls = []
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    # Assignment with function call
                    if isinstance(node.value, ast.Call):
                        call_ctx = self._parse_call_node(node.value)
                        if call_ctx and len(node.targets) > 0:
                            if isinstance(node.targets[0], ast.Name):
                                call_ctx.assigned_to = node.targets[0].id
                        if call_ctx:
                            calls.append(call_ctx)
                
                elif isinstance(node, ast.Expr):
                    # Standalone function call
                    if isinstance(node.value, ast.Call):
                        call_ctx = self._parse_call_node(node.value)
                        if call_ctx:
                            calls.append(call_ctx)
        
        except SyntaxError:
            # Not valid Python, try regex-based extraction
            calls = self._regex_extract_calls(code)
        
        return calls
    
    def _parse_call_node(self, node: ast.Call) -> Optional[FunctionCallContext]:
        """Parse an AST Call node into FunctionCallContext"""
        if not isinstance(node.func, ast.Name):
            return None
        
        func_name = node.func.id
        
        # Extract positional arguments
        pos_args = []
        for arg in node.args:
            pos_args.append(self._ast_to_string(arg))
        
        # Extract keyword arguments
        kw_args = {}
        for keyword in node.keywords:
            kw_args[keyword.arg] = self._ast_to_string(keyword.value)
        
        return FunctionCallContext(
            function_name=func_name,
            positional_args=pos_args,
            keyword_args=kw_args,
            call_line=getattr(node, 'lineno', 0)
        )
    
    def _ast_to_string(self, node: ast.AST) -> str:
        """Convert AST node to string representation"""
        if isinstance(node, ast.Constant):
            return repr(node.value)
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Str):
            return repr(node.s)
        elif isinstance(node, ast.Num):
            return str(node.n)
        else:
            return ast.unparse(node) if hasattr(ast, 'unparse') else str(node)
    
    def _regex_extract_calls(self, code: str) -> List[FunctionCallContext]:
        """Extract function calls using regex (fallback for invalid Python)"""
        calls = []
        
        # Pattern: var = func_name(args)
        pattern = r'(\w+)\s*=\s*(\w+)\s*\((.*?)\)'
        
        for match in re.finditer(pattern, code):
            var_name = match.group(1)
            func_name = match.group(2)
            args_str = match.group(3)
            
            # Parse arguments
            pos_args = []
            kw_args = {}
            
            if args_str.strip():
                for arg in args_str.split(','):
                    arg = arg.strip()
                    if '=' in arg:
                        key, val = arg.split('=', 1)
                        kw_args[key.strip()] = val.strip()
                    else:
                        pos_args.append(arg)
            
            calls.append(FunctionCallContext(
                function_name=func_name,
                positional_args=pos_args,
                keyword_args=kw_args,
                assigned_to=var_name
            ))
        
        return calls
    
    def _detect_changes(
        self,
        previous_calls: List[FunctionCallContext],
        current_calls: List[FunctionCallContext],
        context: ChangeContext
    ) -> ChangeContext:
        """Detect what changed between previous and current function calls"""
        
        prev_by_func = {c.function_name: c for c in previous_calls}
        curr_by_func = {c.function_name: c for c in current_calls}
        
        # Check for new function calls
        new_functions = set(curr_by_func.keys()) - set(prev_by_func.keys())
        if new_functions:
            context.change_type = 'new_call'
            context.affected_functions = list(new_functions)
            return context
        
        # Check for parameter changes in existing functions
        for func_name in curr_by_func:
            if func_name not in prev_by_func:
                continue
            
            prev_call = prev_by_func[func_name]
            curr_call = curr_by_func[func_name]
            
            # Check positional args
            if len(curr_call.positional_args) > len(prev_call.positional_args):
                context.change_type = 'param_added'
                context.affected_functions.append(func_name)
                # Record new parameters
                for i in range(len(prev_call.positional_args), len(curr_call.positional_args)):
                    context.new_parameters[f'arg_{i}'] = curr_call.positional_args[i]
            
            # Check keyword args
            prev_kwargs = set(prev_call.keyword_args.keys())
            curr_kwargs = set(curr_call.keyword_args.keys())
            new_kwargs = curr_kwargs - prev_kwargs
            
            if new_kwargs:
                context.change_type = 'param_added'
                context.affected_functions.append(func_name)
                for kw in new_kwargs:
                    context.new_parameters[kw] = curr_call.keyword_args[kw]
            
            # Check if parameter values changed (especially data sources)
            for kw in prev_kwargs & curr_kwargs:
                if prev_call.keyword_args[kw] != curr_call.keyword_args[kw]:
                    context.change_type = 'data_source_changed' if 'source' in kw else 'param_changed'
                    context.affected_functions.append(func_name)
                    context.new_parameters[kw] = curr_call.keyword_args[kw]
        
        return context
    
    def _infer_data_context(
        self,
        call: FunctionCallContext,
        full_code: str
    ) -> Optional[DataContext]:
        """
        Infer data context from function call.
        
        Looks for clues like:
        - 'source' parameter pointing to a CSV file
        - Known dataset names
        - Variable names
        """
        data_ctx = DataContext(variable_name=call.assigned_to)
        
        # Check for source parameter
        if 'source' in call.keyword_args:
            source = call.keyword_args['source'].strip('\'"')
            data_ctx.source_file = source
            
            # # Try to infer schema from filename
            # for dataset_name, schema in self.known_schemas.items():
            #     if dataset_name.lower() in source.lower():
            #         data_ctx.inferred_schema = schema
            #         data_ctx.context_hints.append(f"Dataset: {dataset_name}")
            #         break
        
        # Check function name for hints
        if 'load' in call.function_name.lower() or 'read' in call.function_name.lower():
            data_ctx.context_hints.append("Data loading function")
        
        if 'preprocess' in call.function_name.lower():
            data_ctx.context_hints.append("Data preprocessing function")
        
        return data_ctx if (data_ctx.source_file or data_ctx.context_hints) else None
    
    def get_function_generation_context(
        self,
        function_name: str,
        change_context: ChangeContext,
        current_code: str
    ) -> Dict[str, Any]:
        """
        Get all relevant context for generating a specific function.
        
        Returns:
            Dict with:
            - function_name
            - parameters (signature)
            - data_context (if applicable)
            - hints (list of hints for generation)
            - should_regenerate (bool)
        """
        # Find the function call in current code
        calls = self._extract_function_calls(current_code)
        target_call = next((c for c in calls if c.function_name == function_name), None)
        
        if not target_call:
            return {}
        
        # Build context
        gen_context = {
            'function_name': function_name,
            'parameters': {
                'positional': target_call.positional_args,
                'keyword': target_call.keyword_args
            },
            'hints': [],
            'should_regenerate': function_name in change_context.affected_functions
        }
        
        # Add data context if available
        if target_call.assigned_to and target_call.assigned_to in change_context.data_contexts:
            data_ctx = change_context.data_contexts[target_call.assigned_to]
            gen_context['data_context'] = {
                'source_file': data_ctx.source_file,
                'schema': data_ctx.inferred_schema,
                'hints': data_ctx.context_hints
            }
            
            # Add specific hints based on data context
            if data_ctx.source_file:
                gen_context['hints'].append(f"Loading data from {data_ctx.source_file}")
            
            if data_ctx.inferred_schema:
                schema_hint = f"Expected columns: {', '.join(data_ctx.inferred_schema.keys())}"
                gen_context['hints'].append(schema_hint)
        
        # Add change-specific hints
        if change_context.change_type == 'param_added':
            gen_context['hints'].append("New parameters added - update function signature and logic")
        elif change_context.change_type == 'data_source_changed':
            gen_context['hints'].append("Data source changed - adapt logic to new dataset")
        
        return gen_context
