"""
Function Implementation Generator

Generates complete, working function implementations for undefined function calls.
Uses LLM to create library-quality implementations with proper imports and bodies.
"""

import ast
import os
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any

from parser import IntentNode


@dataclass
class FunctionSignature:
    """Represents a function signature extracted from a call"""
    name: str
    positional_args: List[str]  # Argument names
    keyword_args: Dict[str, str]  # arg_name -> default_value
    call_node_id: str  # Node ID of the function call


@dataclass
class GeneratedImplementation:
    """Represents a generated function implementation"""
    function_name: str
    imports: List[str]  # Import statements needed
    function_def: str  # Complete function definition
    signature: FunctionSignature
    confidence: float  # 0.0 to 1.0


class ImplementationGenerator:
    """Generate complete implementations for undefined functions"""

    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize the implementation generator.

        Args:
            openai_api_key: OpenAI API key (or use OPENAI_API_KEY env var)
        """
        self.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')

        if not self.api_key:
            print("Warning: OpenAI API key not provided. Implementation generation will be disabled.")
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

    def analyze_undefined_functions(
        self,
        nodes: List[IntentNode],
        context: str
    ) -> List[FunctionSignature]:
        """
        Analyze nodes to find undefined function calls.

        Args:
            nodes: Parsed intent nodes
            context: Original semiformal code

        Returns:
            List of function signatures that need implementations
        """
        # Find all function calls
        function_calls = [n for n in nodes if n.type == 'function_call']

        # Find all function definitions
        defined_functions = set()
        for node in nodes:
            if node.type == 'function_def':
                defined_functions.add(node.content)

        # Also check if functions are defined in the context
        try:
            tree = ast.parse(context)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    defined_functions.add(node.name)
        except:
            pass

        # Find undefined function calls
        undefined = []
        for call_node in function_calls:
            func_name = call_node.content
            if func_name not in defined_functions and not self._is_builtin_or_library(func_name):
                # Extract signature from the call
                sig = self._extract_signature_from_call(call_node, nodes)
                undefined.append(sig)

        return undefined

    def _is_builtin_or_library(self, func_name: str) -> bool:
        """Check if function is a builtin or common library function"""
        # Common builtins and library functions that don't need implementation
        known_functions = {
            # Builtins
            'print', 'len', 'range', 'enumerate', 'zip', 'map', 'filter',
            'open', 'input', 'int', 'str', 'float', 'list', 'dict', 'set',
            'sum', 'min', 'max', 'sorted', 'reversed',
            # Common pandas
            'read_csv', 'DataFrame', 'Series',
            # Common numpy
            'array', 'zeros', 'ones', 'arange',
            # Common matplotlib
            'plot', 'scatter', 'hist', 'show', 'xlabel', 'ylabel', 'title',
        }
        return func_name in known_functions

    def _extract_signature_from_call(
        self,
        call_node: IntentNode,
        all_nodes: List[IntentNode]
    ) -> FunctionSignature:
        """Extract function signature from a function call node"""
        func_name = call_node.content

        # Get argument node IDs from metadata
        arg_node_ids = call_node.metadata.get('arg_node_ids', [])
        kwarg_node_ids = call_node.metadata.get('kwarg_node_ids', {})

        # Build positional arguments
        positional_args = []
        for arg_id in arg_node_ids:
            arg_node = next((n for n in all_nodes if n.id == arg_id), None)
            if arg_node:
                # Use the content as parameter name (or type hint)
                positional_args.append(arg_node.content)

        # Build keyword arguments
        keyword_args = {}
        for kwarg_name, kwarg_node_id in kwarg_node_ids.items():
            kwarg_node = next((n for n in all_nodes if n.id == kwarg_node_id), None)
            if kwarg_node:
                keyword_args[kwarg_name] = kwarg_node.content

        return FunctionSignature(
            name=func_name,
            positional_args=positional_args,
            keyword_args=keyword_args,
            call_node_id=call_node.id
        )

    def generate_implementation(
        self,
        signature: FunctionSignature,
        context: str,
        intent: str = None
    ) -> Optional[GeneratedImplementation]:
        """
        Generate a complete implementation for a function.

        Args:
            signature: Function signature to implement
            context: Semiformal code context
            intent: Optional intent/description of what the function should do

        Returns:
            Generated implementation or None if generation fails
        """
        if not self.client:
            return self._generate_stub_implementation(signature)

        # Build prompt for implementation generation
        prompt = self._build_implementation_prompt(signature, context, intent)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",  # Use more capable model for implementation
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert Python developer. Generate complete, working function implementations with proper imports, type hints, concise docstrings, and error handling."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )

            generated_text = response.choices[0].message.content.strip()

            # Parse the generated implementation
            implementation = self._parse_generated_implementation(
                generated_text, signature
            )

            return implementation

        except Exception as e:
            print(f"Error generating implementation for {signature.name}: {e}")
            return self._generate_stub_implementation(signature)

    def _build_implementation_prompt(
        self,
        signature: FunctionSignature,
        context: str,
        intent: str = None
    ) -> str:
        """Build prompt for implementation generation"""
        # Build parameter list
        params = []
        for i, pos_arg in enumerate(signature.positional_args):
            params.append(pos_arg)

        for kwarg_name, default_val in signature.keyword_args.items():
            params.append(f"{kwarg_name}={default_val}")

        param_str = ', '.join(params)

        prompt_parts = [
            f"Generate a complete, working implementation for the function `{signature.name}`.",
            "",
            "**Function signature:**",
            f"```python",
            f"def {signature.name}({param_str}):",
            "    ...",
            "```",
            "",
        ]

        if intent:
            prompt_parts.extend([
                f"**Intent:** {intent}",
                "",
            ])

        prompt_parts.extend([
            "**Context:**",
            "```python",
            context.strip(),
            "```",
            "",
            "**Requirements:**",
            "1. Generate ALL necessary import statements",
            "2. Include a clear but super concise docstring explaining what the function does (maximum 20 words)",
            "3. Implement the function body with proper logic",
            "4. Use type hints if appropriate",
            "5. Include basic error handling",
            "6. Make it production-ready, library-quality code",
            "",
            "**Output format:**",
            "```python",
            "# Imports (if needed)",
            "import pandas as pd",
            "",
            "def function_name(param1, param2=default):",
            '    """Brief docstring (maximum 20 words)."""',
            "    # Implementation",
            "    ...",
            "```",
            "",
            "Generate the complete implementation now:",
        ])

        return '\n'.join(prompt_parts)

    def _parse_generated_implementation(
        self,
        generated_text: str,
        signature: FunctionSignature
    ) -> GeneratedImplementation:
        """Parse generated implementation text into structured format"""
        # Extract code from markdown if present
        import re
        match = re.search(r'```python\n(.*?)\n```', generated_text, re.DOTALL)
        if match:
            code = match.group(1)
        else:
            code = generated_text

        # Parse the code to extract imports and function def
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # If parsing fails, return as-is
            return GeneratedImplementation(
                function_name=signature.name,
                imports=[],
                function_def=code,
                signature=signature,
                confidence=0.5
            )

        # Extract imports
        imports = []
        function_def = None

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(ast.unparse(node))
            elif isinstance(node, ast.FunctionDef) and node.name == signature.name:
                function_def = ast.unparse(node)

        if not function_def:
            # Couldn't find the function, use the whole code
            function_def = code

        return GeneratedImplementation(
            function_name=signature.name,
            imports=imports,
            function_def=function_def,
            signature=signature,
            confidence=0.9
        )

    def _generate_stub_implementation(
        self,
        signature: FunctionSignature
    ) -> GeneratedImplementation:
        """Generate a stub implementation when LLM is not available"""
        # Build parameter list
        params = []
        for pos_arg in signature.positional_args:
            params.append(pos_arg)

        for kwarg_name, default_val in signature.keyword_args.items():
            params.append(f"{kwarg_name}={default_val}")

        param_str = ', '.join(params)

        function_def = f"""def {signature.name}({param_str}):
    \"\"\"TODO: Implement this function.\"\"\"
    raise NotImplementedError("Function {signature.name} needs implementation")"""

        return GeneratedImplementation(
            function_name=signature.name,
            imports=[],
            function_def=function_def,
            signature=signature,
            confidence=0.0
        )

    def generate_complete_code(
        self,
        nodes: List[IntentNode],
        context: str,
        base_code: str
    ) -> Tuple[str, List[GeneratedImplementation]]:
        """
        Generate complete code with implementations for all undefined functions.

        Args:
            nodes: Parsed intent nodes
            context: Original semiformal code
            base_code: Base generated Python code

        Returns:
            (complete_code, list_of_implementations)
        """
        # Find undefined functions
        undefined_sigs = self.analyze_undefined_functions(nodes, context)

        if not undefined_sigs:
            return base_code, []

        # Generate implementations
        implementations = []
        for sig in undefined_sigs:
            # Try to infer intent from function name and context
            intent = self._infer_intent(sig, context)
            impl = self.generate_implementation(sig, context, intent)
            if impl:
                implementations.append(impl)

        # Build complete code
        complete_code = self._assemble_complete_code(base_code, implementations)

        return complete_code, implementations

    def _infer_intent(self, signature: FunctionSignature, context: str) -> str:
        """Infer the intent of a function from its name and context"""
        # Simple heuristic: use function name as intent
        name_parts = signature.name.replace('_', ' ')
        return f"Function to {name_parts}"

    def _assemble_complete_code(
        self,
        base_code: str,
        implementations: List[GeneratedImplementation]
    ) -> str:
        """Assemble complete code with implementations"""
        if not implementations:
            return base_code

        # Collect all imports
        all_imports = set()
        for impl in implementations:
            all_imports.update(impl.imports)

        # Collect all function definitions
        function_defs = []
        for impl in implementations:
            function_defs.append(impl.function_def)

        # Build the complete code structure
        parts = []

        # 1. Imports
        if all_imports:
            parts.extend(sorted(all_imports))
            parts.append("")  # Blank line

        # 2. Function definitions
        for func_def in function_defs:
            parts.append(func_def)
            parts.append("")  # Blank line

        # 3. Original code (calls, etc.)
        parts.append(base_code)

        return '\n'.join(parts)