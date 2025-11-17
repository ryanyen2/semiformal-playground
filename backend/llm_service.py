"""
Unified LLM Service

Single LLM call for code generation:
- Full code generation (from scratch)
- Git diff format generation (for edits)
"""

import os
import ast
import re
from typing import Optional, Dict, Any, List, Tuple
from config import MVPConfig, DEFAULT_CONFIG


class LLMService:
    """Unified service for all LLM operations - single call approach"""
    
    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        config: Optional[MVPConfig] = None
    ):
        """
        Initialize LLM service.
        
        Args:
            openai_api_key: OpenAI API key (or use OPENAI_API_KEY env var)
            config: Configuration object (uses DEFAULT_CONFIG if None)
        """
        self.config = config or DEFAULT_CONFIG
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
            except Exception as e:
                print(f"Warning: Failed to initialize OpenAI client: {e}")
                self.client = None
    
    def generate_code(
        self,
        annotated_semiformal: str,
        existing_python: str = "",
        target_nodes: List[Dict[str, Any]] = None,
        trigger_type: str = "initial",
        previous_semiformal: str = ""
    ) -> Tuple[str, bool]:
        """
        Generate Python code from annotated semiformal code.
        
        Single LLM call that generates:
        - Full Python code if existing_python is empty
        - Git diff format if existing_python is provided
        
        Args:
            annotated_semiformal: Semiformal code annotated with parsed nodes
            existing_python: Existing Python code (empty for full generation)
            target_nodes: Optional list of target nodes that need generation
            
        Returns:
            (generated_code_or_diff, success)
        """
        if not self.client:
            return self._create_placeholder_from_nodes(target_nodes), False
        
        prompt = self._build_unified_prompt(
            annotated_semiformal=annotated_semiformal,
            existing_python=existing_python,
            target_nodes=target_nodes,
            trigger_type=trigger_type,
            previous_semiformal=previous_semiformal,
        )
        
        max_retries = self.config.generator.max_llm_retries
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a Python code generator. Generate valid, executable Python code. If existing code is provided, generate a git diff format patch."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.config.llm.temperature,
                    max_tokens=self.config.llm.max_tokens
                )
                
                generated = response.choices[0].message.content.strip()
                if not generated:
                    raise ValueError("LLM returned empty response")
                
                # Extract code or diff
                if existing_python:
                    # Expecting git diff format
                    diff = self._extract_diff(generated)
                    if diff:
                        return diff, True
                    # Fallback: try to extract code block
                    code = self._extract_code_block(generated)
                    if code:
                        # Convert to diff format
                        return self._code_to_diff(existing_python, code), True
                else:
                    # Expecting full code
                    code = self._extract_code_block(generated)
                    if code:
                        if self.config.generator.validate_generated_code:
                            validation_error = self._validate_python_code(code)
                            if validation_error:
                                raise ValueError(f"Generated code validation failed: {validation_error}")
                        return code, True
                
                raise ValueError("Could not extract code or diff from LLM response")
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"LLM generation attempt {attempt + 1} failed: {str(e)}. Retrying...")
                    continue
                else:
                    print(f"LLM generation failed after {max_retries} attempts: {str(e)}")
        
        return self._create_placeholder_from_nodes(target_nodes), False
    
    def _build_unified_prompt(
        self,
        annotated_semiformal: str,
        existing_python: str = "",
        target_nodes: List[Dict[str, Any]] = None,
        trigger_type: str = "initial",
        previous_semiformal: str = ""
    ) -> str:
        """Build unified prompt for anchor-based code generation"""
        
        prompt_parts = [
            "# Python Code Generation with Semantic Anchors",
            "",
            "Generate Python code from semiformal specifications with **anchor comments** that enable precise traceability.",
            "",
            "This is a *single* code-generation call. Use the trigger context below to decide how much of the code to change.",
            "",
            "## Trigger Context",
            f"- Trigger type: `{trigger_type}`",
        ]

        if previous_semiformal:
            prompt_parts.extend(
                [
                    "- You are updating existing code based on a **changed semiformal spec** (see previous vs updated spec below).",
                    "",
                ]
            )
        else:
            prompt_parts.extend(
                [
                    "- You are either generating code from scratch or updating code without an explicit previous spec.",
                    "",
                ]
            )
        
        # Add mode-specific instructions
        if existing_python and existing_python.strip():
            prompt_parts.extend(_build_diff_mode_prompt(annotated_semiformal, existing_python))
        else:
            prompt_parts.extend(_build_full_generation_prompt(annotated_semiformal))

        # If we have previous (before) semiformal spec, show it explicitly
        if previous_semiformal:
            prompt_parts.extend(
                [
                    "",
                    "## Semiformal Specification (Before Edit)",
                    "```",
                    previous_semiformal.strip(),
                    "```",
                ]
            )

        # Always show the updated / current semiformal spec next (the annotated one
        # is already shown inside the mode-specific block, but we repeat it in raw
        # form so the model can see the plain text as well).
        prompt_parts.extend(
            [
                "",
                "## Semiformal Specification (After Edit, Annotated)",
                "```",
                annotated_semiformal.strip(),
                "```",
            ]
        )
        
        # Add anchor rules (always included)
        prompt_parts.extend([
            "",
            "## Anchor Comment Rules (CRITICAL)",
            "",
            "### Anchor Format",
            "Each line in the semiformal spec has anchor comments like: `#> anchor1; anchor2; anchor3`",
            "You MUST place corresponding anchors in the generated Python code as inline comments using the `#>` prefix.",
            "",
            "### Anchor Types & Placement",
            "",
            "**1. Variable Anchors (e.g., `#> result`, `#> x`, `#> y`)**",
            "   - Place on the line where the variable is FIRST DEFINED",
            "   - Example: `result = pd.read_csv('data.csv')  # result`",
            "",
            "**2. NL Phrase Anchors (e.g., `#> load`, `#> dataset`, `#> process`)**",
            "   - Place on the line implementing that operation",
            "   - If operation spans multiple lines, place on the FIRST line",
            "   - Example: `data = pd.read_csv('data.csv')  # load # dataset`",
            "",
            "**3. Hole/Hint Anchors (e.g., `#> split data into train and test`)**",
            "   - Place on the line(s) implementing the hint",
            "   - If implemented as a function, place on the function definition line",
            "   - Example: `x, y = train_test_split(data, test_size=0.2)  # x # y # split data into train and test`",
            "",
            "**4. Function Call Anchors (e.g., `#> transform`, `#> print`)**",
            "   - Place on the line with the function call",
            "   - Example: `print(output)  # print # output`",
            "",
            "### Anchor Placement Guidelines",
            "",
            "✓ **DO**: Place anchors as inline comments at the end of the line, using `#>`",
            "✓ **DO**: Use multiple anchors on one line if that line implements multiple concepts",
            "✓ **DO**: Place anchors on function definitions if they implement NL phrases or holes",
            "✓ **DO**: Keep anchor order matching the semiformal spec order (left to right)",
            "",
            "✗ **DON'T**: Skip any anchors from the semiformal spec",
            "✗ **DON'T**: Place anchors on import statements",
            "✗ **DON'T**: Place anchors on blank lines or docstrings",
            "✗ **DON'T**: Modify anchor text (use exact text from semiformal)",
            "",
        ])
        
        prompt_parts.extend(_build_examples())
        
        # Add target node focus if specified
        if target_nodes:
            prompt_parts.extend([
                "",
                "## Focus Areas",
                f"Pay special attention to these {len(target_nodes)} node(s):",
            ])
            for node in target_nodes:
                node_type = node.get('type', 'unknown')
                value = node.get('value', '')
                prompt_parts.append(f"  - {node_type}: `{value}`")
        
        prompt_parts.extend([
            "",
            "## Your Task",
            "Generate Python code following ALL anchor rules above. Ensure every anchor from the semiformal spec appears in your code.",
        ])
        
        return '\n'.join(prompt_parts)
    
    def _extract_code_block(self, response: str) -> str:
        """Extract code from markdown code block"""
        match = re.search(r'```python\n(.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)
        
        match = re.search(r'```\n(.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)
        
        return response
    
    def _extract_diff(self, response: str) -> Optional[str]:
        """Extract git diff from response"""
        # Look for diff markers
        if '---' in response and '+++' in response:
            # Extract diff section
            lines = response.split('\n')
            diff_start = None
            for i, line in enumerate(lines):
                if line.startswith('---') or line.startswith('diff --git'):
                    diff_start = i
                    break
            
            if diff_start is not None:
                return '\n'.join(lines[diff_start:])
        
        # Try to find diff in code block
        match = re.search(r'```diff\n(.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)
        
        match = re.search(r'```\n(.*?---.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)
        
        return None
    
    def _code_to_diff(self, old_code: str, new_code: str) -> str:
        """Convert two code versions to a simple diff format"""
        # Simple line-by-line diff
        old_lines = old_code.split('\n')
        new_lines = new_code.split('\n')
        
        # Use difflib for proper diff generation
        import difflib
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
            fromfile='old.py',
            tofile='new.py'
        )
        return '\n'.join(diff)
    
    def _validate_python_code(self, code: str) -> Optional[str]:
        """Validate that code is syntactically correct Python"""
        if not code or not code.strip():
            return "Code is empty"
        
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"Syntax error: {e.msg} at line {e.lineno}"
        except Exception as e:
            return f"Validation error: {str(e)}"
    
    def _create_placeholder_from_nodes(self, target_nodes: List[Dict[str, Any]] = None) -> str:
        """Create placeholder code when LLM is unavailable"""
        if not target_nodes:
            return "# TODO: Fill this"
        
        # Extract target names from nodes
        target_names = []
        for node in target_nodes:
            if node.get('type') == 'identifier' and node.get('metadata', {}).get('role') == 'target':
                target_names.append(node.get('content', ''))
        
        if not target_names:
            return "# TODO: Fill this"
        
        if len(target_names) == 1:
            return f"{target_names[0]} = None  # TODO: Fill this placeholder"
        else:
            targets = ', '.join(target_names)
            values = ', '.join(['None'] * len(target_names))
            return f"{targets} = {values}  # TODO: Fill these placeholders"


def _build_full_generation_prompt(annotated_semiformal: str) -> List[str]:
    """Build prompt for full code generation"""
    return [
        "## Mode: Full Code Generation",
        "",
        "**Input - Annotated Semiformal Specification:**",
        "```",
        annotated_semiformal.strip(),
        "```",
        "",
        "**Output Format:**",
        "```python",
        "# Your complete Python code here",
        "# Include all imports",
        "# Include anchor comments as specified, using the `#>` prefix (e.g., `#> x; load`).",
        "```",
        "",
        "**Requirements:**",
        "1. Generate complete, executable Python code",
        "2. Include all necessary imports at the top (no anchors on imports)",
        "3. Place anchor comments exactly as specified in rules",
        "4. Code should be well-structured, correct, and follow best practices",
        "5. Every anchor from the semiformal spec must appear in generated code",
    ]


def _build_diff_mode_prompt(annotated_semiformal: str, existing_python: str) -> List[str]:
    """Build prompt for diff generation"""
    return [
        "## Mode: Git Diff Generation",
        "",
        "**Existing Python Code:**",
        "```python",
        existing_python.strip(),
        "```",
        "",
        "**Updated Annotated Semiformal Specification:**",
        "```",
        annotated_semiformal.strip(),
        "```",
        "",
        "**Output Format (Git Unified Diff):**",
        "```diff",
        "--- a/code.py",
        "+++ b/code.py",
        "@@ -line,count +line,count @@",
        " context line",
        "-removed line",
        "+added line",
        " context line",
        "```",
        "",
        "**Requirements:**",
        "1. Generate a git unified diff format patch",
        "2. Include 3 lines of context before/after changes",
        "3. Lines starting with `-` are removed",
        "4. Lines starting with `+` are added",
        "5. Lines starting with ` ` (space) are context (unchanged)",
        "6. Update or add anchor comments as needed",
        "7. Use proper hunk headers: `@@ -start,count +start,count @@`",
        "8. Ensure all anchors from updated semiformal spec are present",
    ]


def _build_examples() -> List[str]:
    """Build comprehensive examples section"""
    return [
        "## Examples",
        "",
        "### Example 1: Simple Pipeline",
        "",
        "**Input Semiformal:**",
        "```",
        "#> result; load; dataset; process",
        "result = load the dataset and process it",
        "",
        "# output; transform; result",
        "output = transform(result)",
        "",
        "# print; output",
        "print(output)",
        "```",
        "",
        "**Correct Output:**",
        "```python",
        "import pandas as pd",
        "",
        "# Load and process dataset",
        "data = pd.read_csv('data.csv')  #> load; dataset",
        "processed_data = data.dropna()  #> process",
        "result = processed_data  #> result",
        "",
        "# Transform the result",
        "output = result.apply(lambda x: x * 2)  #> output; transform; result",
        "",
        "# Print output",
        "print(output)  #> print; output",
        "```",
        "",
        "**Explanation:**",
        "- `# load # dataset` marks where data loading happens",
        "- `# process` marks the processing step",
        "- `# result` marks where result variable is defined",
        "- `# output # transform` marks both the output variable and transform operation",
        "- Multiple anchors on same line when one line implements multiple concepts",
        "",
        "---",
        "",
        "### Example 2: Hole Implementation",
        "",
        "**Input Semiformal:**",
        "```",
        "#> x; y; split data into train and test",
        "x, y = {split data into train and test}",
        "```",
        "",
        "**Correct Output:**",
        "```python",
        "from sklearn.model_selection import train_test_split",
        "",
        "# Split data into train and test sets",
        "x, y = train_test_split(data, test_size=0.2, random_state=42)  #> x; y; split data into train and test",
        "```",
        "",
        "**Explanation:**",
        "- All three anchors on one line because the operation is atomic",
        "- Hole hint becomes an anchor exactly as written",
        "",
        "---",
        "",
        "### Example 3: Function Definition for NL Phrase",
        "",
        "**Input Semiformal:**",
        "```",
        "#> cleaned; remove; outliers; normalize",
        "cleaned = remove outliers and normalize(data)",
        "```",
        "",
        "**Correct Output:**",
        "```python",
        "import numpy as np",
        "from sklearn.preprocessing import StandardScaler",
        "",
        "def remove_outliers_and_normalize(df):  #> remove; outliers; normalize",
        '    """Remove outliers and normalize data"""',
        "    # Remove outliers using IQR method",
        "    Q1 = df.quantile(0.25)",
        "    Q3 = df.quantile(0.75)",
        "    IQR = Q3 - Q1",
        "    df_filtered = df[~((df < (Q1 - 1.5 * IQR)) | (df > (Q3 + 1.5 * IQR))).any(axis=1)]",
        "    ",
        "    # Normalize",
        "    scaler = StandardScaler()",
        "    df_normalized = pd.DataFrame(",
        "        scaler.fit_transform(df_filtered),",
        "        columns=df_filtered.columns",
        "    )",
        "    return df_normalized",
        "",
        "# Apply cleaning and normalization",
        "cleaned = remove_outliers_and_normalize(data)  #> cleaned",
        "```",
        "",
        "**Explanation:**",
        "- NL phrase anchors on function definition line (where implementation starts)",
        "- Variable anchor on the call site (where variable is defined)",
        "",
        "---",
        "",
        "### Example 4: Git Diff Format",
        "",
        "**Existing Code:**",
        "```python",
        "import pandas as pd",
        "",
        "data = pd.read_csv('data.csv')",
        "result = data.dropna()",
        "print(result)",
        "```",
        "",
        "**Updated Semiformal:**",
        "```",
        "#> result; load; dataset",
        "result = load the dataset",
        "",
        "#> cleaned; process",
        "cleaned = process(result)",
        "",
        "#> print; cleaned",
        "print(cleaned)",
        "```",
        "",
        "**Correct Diff Output:**",
        "```diff",
        "--- a/code.py",
        "+++ b/code.py",
        "@@ -1,5 +1,8 @@",
        " import pandas as pd",
        " ",
        "-data = pd.read_csv('data.csv')",
        "-result = data.dropna()",
        "-print(result)",
        "+# Load dataset",
        "+data = pd.read_csv('data.csv')  #> load; dataset",
        "+result = data  #> result",
        "+",
        "+# Process data",
        "+cleaned = result.dropna()  #> cleaned; process",
        "+",
        "+print(cleaned)  #> print; cleaned",
        "```",
        "",
        "**Explanation:**",
        "- Diff shows removal of old lines (with `-`)",
        "- Addition of new lines with proper anchors (with `+`)",
        "- Context lines included (with space prefix)",
        "",
    ]

