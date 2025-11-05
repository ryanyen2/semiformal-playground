"""
LLM-based code generator using OpenAI GPT-4o.

Generates complete Python code from semiformal specifications.
"""

import os
from typing import Dict, List, Any, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class CodeGenerator:
    """Generates complete Python code from semiformal specifications."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the code generator.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.client = OpenAI(api_key=api_key or os.getenv('OPENAI_API_KEY'))
        self.model = "gpt-4o"

    def generate_function(
        self,
        func_name: str,
        params: List[str],
        context: str,
        constraints: Optional[List[str]] = None
    ) -> str:
        """
        Generate a complete function implementation.

        Args:
            func_name: Name of the function
            params: List of parameter names
            context: Code context showing how the function is used
            constraints: Additional constraints (comments, partial code)

        Returns:
            Complete function implementation as string
        """
        prompt = self._build_function_prompt(func_name, params, context, constraints)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are an expert Python programmer. Generate clean, efficient Python code based on specifications."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )

        generated_code = response.choices[0].message.content
        return self._extract_code(generated_code)

    def generate_expression(
        self,
        var_name: str,
        nl_description: str,
        context: str
    ) -> str:
        """
        Generate a Python expression from natural language.
`
        Args:
            var_name: Variable name
            nl_description: Natural language description
            context: Surrounding code context

        Returns:
            Python expression as string
        """
        prompt = f"""Generate a Python expression for the following specification:

Variable: {var_name}
Description: {nl_description}

Context:
```python
{context}
```

Provide only the right-hand side of the assignment (the expression), without the variable name or '='."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are an expert Python programmer. Generate concise Python expressions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=200
        )

        return response.choices[0].message.content.strip()

    def regenerate_with_constraints(
        self,
        func_name: str,
        current_code: str,
        new_constraint: str,
        constraint_type: str  # 'comment', 'statement', 'parameter'
    ) -> str:
        """
        Regenerate function body with additional constraints.

        Args:
            func_name: Function name
            current_code: Current function implementation
            new_constraint: New constraint to incorporate
            constraint_type: Type of constraint being added

        Returns:
            Updated function implementation
        """
        prompt = f"""Update the following Python function based on a new constraint:

Current implementation:
```python
{current_code}
```

Constraint type: {constraint_type}
New constraint: {new_constraint}

Generate the complete updated function implementation."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are an expert Python programmer. Update code based on new constraints."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )

        generated_code = response.choices[0].message.content
        return self._extract_code(generated_code)

    def _build_function_prompt(
        self,
        func_name: str,
        params: List[str],
        context: str,
        constraints: Optional[List[str]] = None
    ) -> str:
        """Build a prompt for function generation."""
        constraints_str = ""
        if constraints:
            constraints_str = "\n\nAdditional constraints:\n" + "\n".join(f"- {c}" for c in constraints)

        return f"""Generate a Python function with the following specification:

Function name: {func_name}
Parameters: {', '.join(params) if params else 'none'}

Usage context:
```python
{context}
```
{constraints_str}

Provide a complete, working Python function implementation."""

    def _extract_code(self, response: str) -> str:
        """Extract clean Python code from LLM response."""
        # Remove markdown code fences if present
        lines = response.strip().split('\n')

        # Find code block boundaries
        start_idx = 0
        end_idx = len(lines)

        for i, line in enumerate(lines):
            if line.strip().startswith('```'):
                if start_idx == 0:
                    start_idx = i + 1
                else:
                    end_idx = i
                    break

        code_lines = lines[start_idx:end_idx]
        return '\n'.join(code_lines).strip()


class IncrementalGenerator:
    """Handles incremental code generation and updates."""

    def __init__(self, generator: CodeGenerator):
        self.generator = generator
        self.generation_cache: Dict[str, str] = {}

    def generate_from_parse_result(
        self,
        parse_result: Dict[str, Any],
        original_code: str
    ) -> str:
        """
        Generate complete code from parse result.

        Args:
            parse_result: Result from IncompletePythonParser
            original_code: Original semiformal code

        Returns:
            Complete Python code
        """
        generated_code = parse_result['annotated_code']
        incomplete_parts = parse_result['incomplete_parts']

        # Generate implementations for each incomplete part
        for part in incomplete_parts:
            if part['type'] == 'function':
                # Extract function stub from annotated code
                func_impl = self.generator.generate_function(
                    func_name=part['name'],
                    params=[],  # Will be inferred from stub
                    context=part['context']
                )

                # Replace stub with generated implementation
                stub_pattern = f"def {part['name']}(.*?):\n    ..."
                generated_code = self._replace_stub_with_impl(
                    generated_code,
                    part['name'],
                    func_impl
                )

                # Cache the generation
                self.generation_cache[part['name']] = func_impl

            elif part['type'] == 'nl_text':
                # Generate expression from natural language
                expr = self.generator.generate_expression(
                    var_name=part['name'],
                    nl_description=part['value'],
                    context=part['context']
                )

                # Replace NL text with expression
                nl_pattern = f"{part['name']} = ...  # {part['value']}"
                generated_code = generated_code.replace(
                    nl_pattern,
                    f"{part['name']} = {expr}"
                )

                self.generation_cache[part['name']] = expr

        return generated_code

    def _replace_stub_with_impl(
        self,
        code: str,
        func_name: str,
        implementation: str
    ) -> str:
        """Replace a function stub with its implementation."""
        lines = code.split('\n')
        result = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if this is the stub definition
            if f"def {func_name}(" in line and i + 1 < len(lines) and "..." in lines[i + 1]:
                # Skip the stub (def line and ... line)
                result.append(implementation)
                i += 2
                # Skip blank line after stub if present
                if i < len(lines) and not lines[i].strip():
                    i += 1
            else:
                result.append(line)
                i += 1

        return '\n'.join(result)
