"""
MVP Code Generator with OpenAI (Phase 2-3)

Implements:
- Code generation from intent nodes
- Hole filling with LLM
- Placeholder support
- Node→code mapping tracking
"""

import os
import ast
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from parser import IntentNode
from config import MVPConfig, DEFAULT_CONFIG
from implementation_generator import ImplementationGenerator


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


class CodeGenerator:
    """Generate Python code from intent nodes with OpenAI"""

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
        self.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        self.generate_implementations = generate_implementations

        if not self.api_key:
            print("Warning: OpenAI API key not provided. LLM features will be disabled.")
            self.client = None
        else:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except ImportError:
                print("Warning: openai package not installed. Install with: pip install openai")
                self.client = None
            except Exception as e:
                print(f"Warning: Failed to initialize OpenAI client: {e}")
                self.client = None

        # Initialize implementation generator
        if self.generate_implementations:
            self.impl_generator = ImplementationGenerator(openai_api_key=self.api_key)
        else:
            self.impl_generator = None

    def generate_with_mapping(
        self,
        nodes: List[IntentNode],
        context: str = ""
    ) -> Tuple[str, List[Mapping]]:
        """
        Generate Python code from intent nodes and create mappings.

        Args:
            nodes: List of intent nodes from parser
            context: Original semiformal code for context

        Returns:
            (generated_code, mappings)
        """
        # Group nodes by line
        lines_dict: Dict[int, List[IntentNode]] = {}
        for node in nodes:
            line_num = node.span[0]
            if line_num not in lines_dict:
                lines_dict[line_num] = []
            lines_dict[line_num].append(node)

        generated_lines = []
        mappings = []
        current_line = 0

        # Process each line
        for line_num in sorted(lines_dict.keys()):
            line_nodes = lines_dict[line_num]

            # Check if this is pure Python, NL, or hybrid
            has_nl = any(n.type in ('nl_phrase', 'hole') for n in line_nodes)
            has_python = any(n.type in ('identifier', 'function_call', 'literal', 'operator', 'function_def', 'expr_stmt') for n in line_nodes)

            if has_nl:
                # Need LLM generation
                code, line_mappings = self._generate_from_nl(
                    line_nodes, context, current_line
                )
                generated_lines.append(code)
                mappings.extend(line_mappings)
                # Count actual lines generated
                actual_lines = code.count('\n')
                current_line += actual_lines
            elif has_python:
                # Direct reconstruction
                code = self._reconstruct_python(line_nodes)

                # Handle multi-line statements (like function defs)
                if '\n' in code:
                    # Split multi-line code
                    code_lines = code.split('\n')
                    generated_lines.extend(code_lines)
                    current_line += len(code_lines) - 1
                else:
                    generated_lines.append(code)

                # Create 1:1 mappings
                for node in line_nodes:
                    if node.type in ('identifier', 'function_call', 'function_def', 'expr_stmt'):
                        mappings.append(Mapping(
                            node_id=node.id,
                            slices=[CodeSlice(
                                code=code,
                                line_start=current_line - (len(code.split('\n')) - 1),
                                line_end=current_line,
                                ast_nodes=[]
                            )],
                            confidence=1.0,
                            generation_method='direct'
                        ))

            current_line += 1

        final_code = '\n'.join(generated_lines)
        
        # Generate implementations for undefined functions if enabled
        if self.impl_generator:
            final_code, implementations = self.impl_generator.generate_complete_code(
                nodes, context, final_code
            )
            # Store implementations for later reference
            if hasattr(self, 'last_implementations'):
                self.last_implementations = implementations
        
        # Rebuild mappings from the final generated code to get accurate line/col info
        mappings = self._rebuild_mappings_from_ast(final_code, nodes)
        
        return final_code, mappings

    def _reconstruct_python(self, nodes: List[IntentNode]) -> str:
        """
        Reconstruct Python code from nodes.

        For pure Python nodes, we can just concatenate them intelligently.
        """
        # If there's an expr_stmt node (standalone expression), return it
        for node in nodes:
            if node.type == 'expr_stmt':
                return node.metadata.get('full_statement', node.content)

        # If there's a python_stmt node, just return it
        for node in nodes:
            if node.type == 'python_stmt':
                return node.content

        # Check if any node has full_statement metadata (from parser)
        for node in nodes:
            if node.metadata.get('full_statement'):
                return node.metadata['full_statement']

        # Check if any node has full_code metadata (function defs)
        for node in nodes:
            if node.metadata.get('full_code'):
                return node.metadata['full_code']

        # Otherwise, try to build from components
        # Group by role
        targets = [n for n in nodes if n.type == 'identifier' and n.metadata.get('role') == 'target']
        funcs = [n for n in nodes if n.type in ('function_call', 'function_def')]
        refs = [n for n in nodes if n.type == 'identifier' and n.metadata.get('role') == 'reference']
        literals = [n for n in nodes if n.type == 'literal']
        operators = [n for n in nodes if n.type == 'operator']

        # Build assignment if we have targets
        if targets:
            lhs = ', '.join(t.content for t in targets)

            # Build RHS
            if funcs:
                # Function call(s) - handle nested calls
                # For now, just use first func and last ref as simple approximation
                # Full implementation would need to properly reconstruct the call tree
                if len(funcs) > 1:
                    # Nested calls - build from innermost to outermost
                    # Order: funcs are in order of appearance
                    # refs are arguments
                    if refs:
                        # Start with innermost call
                        inner = f"{funcs[-1].content}({refs[-1].content if refs else ''})"
                        # Build outward
                        for i in range(len(funcs) - 2, -1, -1):
                            inner = f"{funcs[i].content}({inner})"
                        rhs = inner
                    else:
                        # No args, just chain the calls
                        rhs = funcs[0].content + '(' * len(funcs) + ')' * len(funcs)
                else:
                    # Single function call
                    func_name = funcs[0].content
                    # Get arguments
                    args = ', '.join(r.content for r in refs) if refs else ''
                    rhs = f"{func_name}({args})"
            elif operators:
                # Expression with operators (e.g., 5 + 3, x * 2)
                # Interleave literals/refs with operators
                all_values = sorted(literals + refs, key=lambda n: n.span[0])
                parts = []

                for i, val in enumerate(all_values):
                    if val.type == 'literal':
                        content = val.content
                        if val.metadata.get('literal_type') == 'str':
                            content = f'"{content}"'
                        parts.append(content)
                    else:
                        parts.append(val.content)

                    # Add operator if there is one
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

        # No targets - might be function definition or expression statement
        func_defs = [n for n in nodes if n.type == 'function_def']
        if func_defs:
            # Function definition
            func_node = func_defs[0]
            # Use full code if available
            if 'full_code' in func_node.metadata:
                return func_node.metadata['full_code']
            else:
                # Otherwise create stub
                params_nodes = [n for n in nodes if n.type == 'parameter']
                params = ', '.join(p.content for p in params_nodes)
                return f"def {func_node.content}({params}):\n    ..."

        if funcs:
            # Reconstruct function call with arguments
            func = funcs[0]
            func_name = func.content
            
            # Check if we have full_call metadata
            if func.metadata.get('full_call'):
                return func.metadata['full_call']
            
            # Otherwise, try to reconstruct from arg nodes
            arg_node_ids = func.metadata.get('arg_node_ids', [])
            kwarg_node_ids = func.metadata.get('kwarg_node_ids', {})
            
            # Build argument list
            args_parts = []
            
            # Add positional arguments
            for arg_node_id in arg_node_ids:
                # Find the node by ID
                arg_node = next((n for n in nodes if n.id == arg_node_id), None)
                if arg_node:
                    args_parts.append(arg_node.content)
            
            # Add keyword arguments
            for kwarg_name, kwarg_node_id in kwarg_node_ids.items():
                kwarg_node = next((n for n in nodes if n.id == kwarg_node_id), None)
                if kwarg_node:
                    args_parts.append(f"{kwarg_name}={kwarg_node.content}")
            
            # If we couldn't reconstruct from metadata, use refs
            if not args_parts and refs:
                args_parts = [r.content for r in refs]
            
            args_str = ', '.join(args_parts)
            return f"{func_name}({args_str})"

        # Fallback - just join everything
        parts = [n.content for n in nodes]
        return ' '.join(parts)

    def _generate_from_nl(
        self,
        nodes: List[IntentNode],
        context: str,
        start_line: int
    ) -> Tuple[str, List[Mapping]]:
        """
        Generate code from natural language or holes using LLM.

        Args:
            nodes: Nodes for this line (mix of identifiers, NL, holes)
            context: Full semiformal code for context
            start_line: Starting line number in generated code

        Returns:
            (generated_code, mappings)
        """
        # Extract components
        identifiers = [n for n in nodes if n.type == 'identifier' and n.metadata.get('role') == 'target']
        nl_phrases = [n for n in nodes if n.type == 'nl_phrase']
        holes = [n for n in nodes if n.type == 'hole']

        # Build the intent description
        if holes:
            # Hole-based generation
            hint = holes[0].content
            if hint:
                intent = f"Fill hole with hint: {hint}"
            else:
                intent = "Fill empty hole (infer from context)"
        elif nl_phrases:
            # NL phrase generation
            intent = ' '.join([n.content for n in nl_phrases])
        else:
            # Placeholder - no LLM needed
            return self._create_placeholder(identifiers), []

        # Generate with LLM
        if self.client:
            code, mappings = self._llm_generate(identifiers, intent, context, start_line, nodes)
            return code, mappings
        else:
            # Fallback without LLM
            return self._create_placeholder(identifiers), []

    def _create_placeholder(self, identifiers: List[IntentNode]) -> str:
        """
        Create a placeholder assignment for unknown values.

        Phase 2: Placeholder support
        """
        if not identifiers:
            return "# TODO: Fill this"

        target_names = [n.content for n in identifiers]

        if len(target_names) == 1:
            return f"{target_names[0]} = None  # TODO: Fill this placeholder"
        else:
            targets = ', '.join(target_names)
            values = ', '.join(['None'] * len(target_names))
            return f"{targets} = {values}  # TODO: Fill these placeholders"

    def _llm_generate(
        self,
        identifiers: List[IntentNode],
        intent: str,
        context: str,
        start_line: int,
        all_nodes: List[IntentNode]
    ) -> Tuple[str, List[Mapping]]:
        """
        Use OpenAI API to generate code with retry logic and validation.

        Phase 3: Hole filling with LLM
        """
        target_names = [n.content for n in identifiers] if identifiers else []

        # Build prompt
        prompt = self._build_generation_prompt(target_names, intent, context, all_nodes)

        # Retry logic
        max_retries = self.config.generator.max_llm_retries
        last_error = None

        for attempt in range(max_retries):
            try:
                # Call OpenAI API with configured parameters
                response = self.client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a Python code generator. Generate only valid, executable Python code."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.config.llm.temperature,
                    max_tokens=self.config.llm.max_tokens
                )

                generated_code = response.choices[0].message.content.strip()

                if not generated_code:
                    raise ValueError("LLM returned empty response")

                # Extract code from markdown if present
                generated_code = self._extract_code_block(generated_code)

                # Validate generated code if configured
                if self.config.generator.validate_generated_code:
                    validation_error = self._validate_python_code(generated_code)
                    if validation_error:
                        raise ValueError(f"Generated code validation failed: {validation_error}")

                # Parse node annotations if present
                mappings = self._parse_node_annotations(generated_code, all_nodes, start_line)

                # Clean up annotations from code
                clean_code = re.sub(r'# \[NODE:.*?\]\n?', '', generated_code).strip()

                # Final validation of clean code
                if self.config.generator.validate_generated_code:
                    validation_error = self._validate_python_code(clean_code)
                    if validation_error and not self.config.generator.fallback_to_placeholder:
                        raise ValueError(f"Clean code validation failed: {validation_error}")

                return clean_code, mappings

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    print(f"LLM generation attempt {attempt + 1} failed: {str(e)}. Retrying...")
                    continue
                else:
                    print(f"LLM generation failed after {max_retries} attempts: {str(e)}")

        # All retries failed - fallback to placeholder if configured
        if self.config.generator.fallback_to_placeholder:
            print(f"Falling back to placeholder due to LLM failure: {last_error}")
            return self._create_placeholder(identifiers), []
        else:
            # Re-raise the last error
            raise last_error

    def _validate_python_code(self, code: str) -> Optional[str]:
        """
        Validate that code is syntactically correct Python.

        Args:
            code: Code to validate

        Returns:
            Error message if invalid, None if valid
        """
        if not code or not code.strip():
            return "Code is empty"

        try:
            ast.parse(code)
            return None  # Valid
        except SyntaxError as e:
            return f"Syntax error: {e.msg} at line {e.lineno}"
        except Exception as e:
            return f"Validation error: {str(e)}"

    def _build_generation_prompt(
        self,
        target_names: List[str],
        intent: str,
        context: str,
        nodes: List[IntentNode]
    ) -> str:
        """
        Build the prompt for LLM generation.

        Creates a context-aware prompt without hardcoded assumptions
        about libraries or implementation details.
        """
        # Get node IDs for annotation if configured
        node_ids = ','.join([n.id for n in nodes])

        # Analyze context to extract relevant information
        context_info = self._analyze_context(context)

        # Build a general, context-aware prompt
        prompt_parts = [
            "Generate Python code for the following intent.",
            "",
            f"**Intent**: {intent}",
            "",
        ]

        # Add target information if available
        if target_names:
            prompt_parts.append(f"**Assignment target(s)**: {', '.join(target_names)}")
        else:
            prompt_parts.append("**Type**: Expression or statement (no assignment)")

        prompt_parts.append("")

        # Add context information
        prompt_parts.extend([
            "**Context** (surrounding semiformal code):",
            "```python",
            context.strip(),
            "```",
            "",
        ])

        # Add extracted context insights
        if context_info['imports']:
            prompt_parts.append(f"**Available imports**: {', '.join(context_info['imports'])}")

        if context_info['defined_vars']:
            prompt_parts.append(f"**Defined variables**: {', '.join(context_info['defined_vars'])}")

        if context_info['defined_funcs']:
            prompt_parts.append(f"**Defined functions**: {', '.join(context_info['defined_funcs'])}")

        if context_info['imports'] or context_info['defined_vars'] or context_info['defined_funcs']:
            prompt_parts.append("")

        # Add requirements
        prompt_parts.extend([
            "**Requirements**:",
            "1. Generate ONLY valid, executable Python code",
            "2. Use appropriate libraries when needed (infer from context)",
            "3. Code should be concise and correct",
        ])

        if target_names:
            prompt_parts.append(f"4. Code must assign to: {', '.join(target_names)}")

        # Add node annotation instruction if configured
        if self.config.generator.include_node_annotations:
            prompt_parts.extend([
                "",
                f"5. Start with this comment: # [NODE:{node_ids}]",
                "",
                "**Example format**:",
                "```python",
                f"# [NODE:{node_ids}]",
                f"{target_names[0] if target_names else 'result'} = # your code here",
                "```",
            ])

        prompt_parts.extend([
            "",
            "**Generate the Python code now**:",
        ])

        return '\n'.join(prompt_parts)

    def _analyze_context(self, context: str) -> Dict[str, List[str]]:
        """
        Analyze context to extract useful information.

        Returns:
            Dict with keys: imports, defined_vars, defined_funcs
        """
        result = {
            'imports': [],
            'defined_vars': [],
            'defined_funcs': [],
        }

        if not context or not context.strip():
            return result

        try:
            # Try to parse as Python
            tree = ast.parse(context)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        result['imports'].append(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    result['imports'].append(node.module)
                elif isinstance(node, ast.FunctionDef):
                    result['defined_funcs'].append(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            result['defined_vars'].append(target.id)
        except SyntaxError:
            # Context contains non-Python (semiformal), extract what we can with regex
            import_matches = re.findall(r'^\s*import\s+(\w+)', context, re.MULTILINE)
            from_matches = re.findall(r'^\s*from\s+(\w+)', context, re.MULTILINE)
            result['imports'].extend(import_matches + from_matches)

            func_matches = re.findall(r'^\s*def\s+(\w+)', context, re.MULTILINE)
            result['defined_funcs'].extend(func_matches)

            var_matches = re.findall(r'^\s*(\w+)\s*=', context, re.MULTILINE)
            result['defined_vars'].extend(var_matches)

        # Remove duplicates
        result['imports'] = list(set(result['imports']))
        result['defined_vars'] = list(set(result['defined_vars']))
        result['defined_funcs'] = list(set(result['defined_funcs']))

        return result

    def _extract_code_block(self, response: str) -> str:
        """Extract code from markdown code block"""
        # Try to find ```python ... ``` block
        match = re.search(r'```python\n(.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)

        # Try to find ``` ... ``` block
        match = re.search(r'```\n(.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)

        # Return as-is if no code block found
        return response

    def _parse_node_annotations(
        self,
        code: str,
        nodes: List[IntentNode],
        start_line: int
    ) -> List[Mapping]:
        """
        Parse [NODE:...] annotations from generated code.

        Example:
        # [NODE:node_5_x,node_5_split]
        X_train, X_test = train_test_split(...)
        """
        mappings = []
        lines = code.split('\n')

        for i, line in enumerate(lines):
            # Look for [NODE:...] annotation
            match = re.search(r'# \[NODE:(.*?)\]', line)
            if match:
                node_ids = [nid.strip() for nid in match.group(1).split(',')]

                # Get the actual code line (next line or same line)
                if i + 1 < len(lines):
                    code_line = lines[i + 1]
                else:
                    code_line = line

                # Remove annotation from code line
                code_line = re.sub(r'# \[NODE:.*?\]', '', code_line).strip()

                if code_line:  # Only create mapping if there's actual code
                    for node_id in node_ids:
                        # Find the node
                        node = next((n for n in nodes if n.id == node_id), None)
                        if node:
                            mappings.append(Mapping(
                                node_id=node_id,
                                slices=[CodeSlice(
                                    code=code_line,
                                    line_start=start_line + i + 1,
                                    line_end=start_line + i + 1,
                                    ast_nodes=[]
                                )],
                                confidence=0.85,  # LLM-generated
                                generation_method='llm_generated'
                            ))

        return mappings

    def _rebuild_mappings_from_ast(
        self,
        generated_code: str,
        nodes: List[IntentNode]
    ) -> List[Mapping]:
        """
        Rebuild mappings from the final generated Python code using tree-based mapping.
        
        Uses formalized tree mapping algorithm with:
        1. Subtree similarity computation
        2. Structural alignment via DP
        3. Token-level mapping
        4. Underspecification detection
        
        Args:
            generated_code: The final generated Python code
            nodes: The intent nodes from parsing
            
        Returns:
            List of accurate Mapping objects
        """
        try:
            from tree_mapper import TreeMapper, MappingAdapter
            
            # Initialize tree mapper
            mapper = TreeMapper()
            
            # Build IR tree from intent nodes
            ir_tree = mapper.build_ir_tree(nodes)
            
            # Build AST tree from generated code
            ast_tree = mapper.build_ast_tree(generated_code)
            
            # Perform tree mapping
            tree_mappings = mapper.map_trees(ir_tree, ast_tree)
            
            # Detect underspecified regions
            underspecified = mapper.detect_underspecified_regions(ast_tree, tree_mappings)
            
            # Log underspecified regions for debugging
            if underspecified:
                print(f"Detected {len(underspecified)} underspecified AST nodes (LLM-generated)")
                for i, node in enumerate(underspecified[:5]):  # Show first 5
                    print(f"  - {node.node_type}: {node.content[:50]}")
                if len(underspecified) > 5:
                    print(f"  ... and {len(underspecified) - 5} more")
            
            # Convert tree mappings to legacy Mapping format
            mappings = MappingAdapter.convert_tree_mappings_to_code_mappings(
                tree_mappings,
                generated_code
            )
            
            # Fill in mappings for unmapped nodes using heuristic
            mapped_node_ids = {m.node_id for m in mappings}
            
            for node in nodes:
                if node.id not in mapped_node_ids:
                    # Heuristic fallback for completely unmapped nodes
                    sf_line = node.span[0]
                    code_lines = generated_code.split('\n')
                    estimated_line = min(sf_line + 1, len(code_lines))
                    
                    # Find a meaningful line
                    while estimated_line <= len(code_lines):
                        if estimated_line > 0 and estimated_line <= len(code_lines):
                            line_content = code_lines[estimated_line - 1].strip()
                            if line_content and not line_content.startswith('#'):
                                break
                        estimated_line += 1
                    
                    if estimated_line <= len(code_lines):
                        mappings.append(Mapping(
                            node_id=node.id,
                            slices=[CodeSlice(
                                code=code_lines[estimated_line - 1] if estimated_line > 0 else "",
                                line_start=estimated_line,
                                line_end=estimated_line,
                                ast_nodes=[]
                            )],
                            confidence=0.3,  # Very low confidence for heuristic
                            generation_method='heuristic_fallback'
                        ))
            
            return mappings
            
        except Exception as e:
            # Fallback to old simple mapping if tree mapper fails
            print(f"Warning: Tree mapper failed ({e}), falling back to simple mapping")
            return self._rebuild_mappings_from_ast_simple(generated_code, nodes)
    
    def _rebuild_mappings_from_ast_simple(
        self,
        generated_code: str,
        nodes: List[IntentNode]
    ) -> List[Mapping]:
        """
        Simple fallback mapping (old algorithm) used when tree mapper fails.
        """
        mappings = []
        
        try:
            tree = ast.parse(generated_code)
        except SyntaxError:
            return []
        
        # Build content lookup
        nodes_by_content: Dict[str, List[IntentNode]] = {}
        for node in nodes:
            content = node.content
            if content not in nodes_by_content:
                nodes_by_content[content] = []
            nodes_by_content[content].append(node)
        
        mapped_nodes = set()
        
        # Simple AST walk and string matching
        for ast_node in ast.walk(tree):
            if isinstance(ast_node, ast.Name):
                var_name = ast_node.id
                if var_name in nodes_by_content:
                    for intent_node in nodes_by_content[var_name]:
                        if intent_node.id not in mapped_nodes:
                            mappings.append(Mapping(
                                node_id=intent_node.id,
                                slices=[CodeSlice(
                                    code=var_name,
                                    line_start=ast_node.lineno,
                                    line_end=ast_node.lineno,
                                    ast_nodes=[ast_node]
                                )],
                                confidence=0.8,
                                generation_method='simple_match'
                            ))
                            mapped_nodes.add(intent_node.id)
                            break
        
        return mappings
    
    def _extract_code_at_location(self, code: str, line: int, col: int) -> str:
        """Extract the code snippet at a specific line and column."""
        lines = code.split('\n')
        if 1 <= line <= len(lines):
            return lines[line - 1].strip()
        return ""
    
    def _get_statement_for_node(self, tree: ast.AST, target_node: ast.AST) -> str:
        """Get the full statement containing a specific AST node."""
        # Find the statement that contains this node
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.stmt):
                # Check if target_node is part of this statement
                for node in ast.walk(stmt):
                    if node is target_node:
                        return ast.unparse(stmt)
        
        # Fallback: try to unparse the node itself
        try:
            return ast.unparse(target_node)
        except:
            return ""

    def fill_hole(
        self,
        hint: str,
        context: str,
        target_var: Optional[str] = None
    ) -> str:
        """
        Fill a hole with optional hint.

        Phase 3: Hole syntax support

        Args:
            hint: Hint text from {hint} or empty string
            context: Surrounding code for context
            target_var: Variable name being assigned to

        Returns:
            Generated code
        """
        if not self.client:
            return f"None  # TODO: Fill hole{' with hint: ' + hint if hint else ''}"

        # Build prompt for hole filling
        prompt = f"""Fill this hole in the code.

Hint: {hint if hint else 'No hint provided, infer from context'}
Target variable: {target_var if target_var else 'unknown'}

Context:
```python
{context}
```

Generate ONLY the expression or statement to fill the hole. Do not include the variable assignment.
Example: If filling `x = {{use pandas to read CSV}}`, return: `pd.read_csv('data.csv')`

Generate now:"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Python code generator. Generate concise code expressions."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
            )

            generated = response.choices[0].message.content.strip()
            # Extract from code block if present
            generated = self._extract_code_block(generated)
            # Remove any leading/trailing quotes or semicolons
            generated = generated.strip('`;\'\"')

            return generated

        except Exception as e:
            print(f"Hole filling error: {str(e)}")
            return f"None  # Error filling hole: {str(e)}"
