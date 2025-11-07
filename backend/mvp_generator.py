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
from mvp_parser import IntentNode


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

    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize code generator.

        Args:
            openai_api_key: OpenAI API key (or use OPENAI_API_KEY env var)
        """
        self.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
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
            has_python = any(n.type in ('identifier', 'function_call', 'literal', 'operator', 'function_def') for n in line_nodes)

            if has_nl:
                # Need LLM generation
                code, line_mappings = self._generate_from_nl(
                    line_nodes, context, current_line
                )
                generated_lines.append(code)
                mappings.extend(line_mappings)
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
                    if node.type in ('identifier', 'function_call', 'function_def'):
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

        return '\n'.join(generated_lines), mappings

    def _reconstruct_python(self, nodes: List[IntentNode]) -> str:
        """
        Reconstruct Python code from nodes.

        For pure Python nodes, we can just concatenate them intelligently.
        """
        # If there's a python_stmt node, just return it
        for node in nodes:
            if node.type == 'python_stmt':
                return node.content

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
                # Function call
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
            func_name = funcs[0].content
            args = ', '.join(r.content for r in refs) if refs else ''
            return f"{func_name}({args})"

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
        Use OpenAI API to generate code.

        Phase 3: Hole filling with LLM
        """
        target_names = [n.content for n in identifiers] if identifiers else []

        # Build prompt
        prompt = self._build_generation_prompt(target_names, intent, context, all_nodes)

        try:
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Using mini for cost efficiency
                messages=[
                    {"role": "system", "content": "You are a Python code generator. Generate only valid Python code."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            generated_code = response.choices[0].message.content.strip()

            # Extract code from markdown if present
            generated_code = self._extract_code_block(generated_code)

            # Parse node annotations if present
            mappings = self._parse_node_annotations(generated_code, all_nodes, start_line)

            # Clean up annotations from code
            clean_code = re.sub(r'# \[NODE:.*?\]\n?', '', generated_code).strip()

            return clean_code, mappings

        except Exception as e:
            print(f"LLM generation error: {str(e)}")
            # Fallback to placeholder
            return self._create_placeholder(identifiers), []

    def _build_generation_prompt(
        self,
        target_names: List[str],
        intent: str,
        context: str,
        nodes: List[IntentNode]
    ) -> str:
        """Build the prompt for LLM generation"""
        # Get node IDs for annotation
        node_ids = ','.join([n.id for n in nodes])

        prompt = f"""Generate Python code for this intent.

Assignment targets: {target_names if target_names else 'none (expression)'}
Intent: {intent}

Context (full semiformal code):
```
{context}
```

Requirements:
1. Return ONLY valid Python code
2. Use common libraries (pandas, numpy, sklearn) when appropriate
"""

        if target_names:
            prompt += f"\n3. Code should assign to: {', '.join(target_names)}"

        prompt += f"""
4. Start your response with a comment: # [NODE:{node_ids}]

Example format:
```python
# [NODE:{node_ids}]
{target_names[0] if target_names else 'result'} = your_generated_code_here
```

Generate the code now:"""

        return prompt

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
