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


# Static system prompt - efficient and reusable
SYSTEM_PROMPT = """You are an expert Python code generator specializing in semiformal programming and data science workflows.

Your task is to generate valid, executable Python code from semiformal specifications with semantic anchors (#>) that enable precise traceability.

## Critical Data Science Reasoning Guidelines

When generating code, think like a data scientist and reason through dependencies:

1. **Data Flow Analysis**: When a data source changes (e.g., dataset name changes from 'iris.csv' to 'titanic.csv'):
   - ALL downstream functions that process this data MUST be updated
   - Example: If `load_csv(source='titanic.csv')` changes, then `preprocessing(data)` must adapt to Titanic dataset characteristics
   - Consider: column names, data types, missing values, categorical encodings specific to the new dataset

2. **Function Signature Changes**: When function signatures change:
   - Update ALL function definitions with new parameters
   - Update ALL function calls to pass correct arguments
   - Update function implementations to use the new parameters

3. **Stripped Function Bodies**: When you see a function with only `pass  # body omitted - will be regenerated`:
   - The function body has been INTENTIONALLY REMOVED
   - You MUST generate a COMPLETE NEW implementation from scratch
   - DO NOT assume or copy from prior implementations
   - Generate based on: function name, parameters, call sites, and data flow context
   - Reason about what the function should do based on its dependencies and dependents

4. **Context-Aware Implementation**: When implementing functions, adapt to the specific data domain:
   - **Titanic dataset**: survival prediction → handle Age/Fare numeric conversion, Sex/Embarked categorical encoding
   - **Iris dataset**: species classification → dropna, convert object columns to category dtype
   - **Stock prices**: time series analysis → calculate returns, moving averages, volatility
   - **Medical records**: patient data → HIPAA anonymization, diagnosis encoding, age binning
   - **Cybersecurity logs**: threat detection → parse timestamps, extract IP addresses, flag anomalies
   - **Sensor data**: IoT/simulation → resample timestamps, interpolate missing, detect outliers
   - **Text corpus**: NLP preprocessing → tokenize, remove stopwords, lemmatize
   - **Image metadata**: computer vision → extract dimensions, normalize paths, validate formats
   - Consider: data types, domain-specific operations, missing value strategies, encoding schemes

5. **Dependency Propagation**: A change in one node affects all downstream nodes:
   - If a variable changes, all functions using that variable should adapt
   - If a function output changes, all consumers should adapt
   - Think: "What would a data scientist change if this data source changed?"

Key principles:
- Generate complete, idiomatic Python code
- Use #> anchors inline at the end of lines to mark semantic elements
- Use #< ONLY for inferred code when no #> exists on that line
- When function signatures change, update ALL callers and implementations
- When data sources change, update ALL dependent function implementations
- When you see stripped functions, generate FRESH implementations (no assumptions from prior code)
- Generate entire new code; backend handles diff computation
- No docstrings, no __main__ blocks
- Follow anchor placement rules precisely
"""

# Anchor rules - static reference
ANCHOR_RULES = """## Anchor Comment Rules (CRITICAL)

### Anchor Format
Each semiformal line has anchors like: `#> anchor1; anchor2; anchor3`
Place these as **inline comments at the end of Python lines** using the `#>` prefix.

### Inferred Code Annotations (`#<`)
**IMPORTANT**: Use `#<` ONLY when there is NO `#>` annotation on that line.
- `#< operation` marks code you inferred (e.g., `df.dropna()  #< drop na`)
- **NEVER** use `#<` on lines with `#>` annotations
- **NEVER** use `#<` on empty lines or non-code lines

### Anchor Types & Placement

**1. Variable Anchors** (e.g., `#> result`, `#> x`)
   - Place at the end of the line where variable is FIRST DEFINED
   - Example: `result = pd.read_csv('data.csv')  #> result`

**2. NL Phrase Anchors** (e.g., `#> load`, `#> dataset`)
   - Place at the end of line implementing that operation
   - Example: `data = pd.read_csv('data.csv')  #> load; dataset`

**3. Hole/Hint Anchors** (e.g., `#> split data into train and test`)
   - Place at the end of line implementing the hint
   - Example: `x, y = train_test_split(data, test_size=0.2)  #> x; y; split data into train and test`

**4. Function Call Anchors** (e.g., `#> transform`)
   - Place at the end of line with the function call

### Guidelines
✓ **DO**: Place anchors inline at end of lines using `#>`
✓ **DO**: Use semicolons for multiple anchors: `#> anchor1; anchor2`
✓ **DO**: Keep anchor order matching semiformal spec (left to right)
✓ **DO**: Update ALL dependent functions when signatures change

✗ **DON'T**: Skip any anchors from semiformal spec
✗ **DON'T**: Place anchors on imports or blank lines
✗ **DON'T**: Use `#<` on lines that have `#>`
✗ **DON'T**: Generate docstrings or __main__ blocks
"""


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
        previous_semiformal: str = "",
        generation_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, bool]:
        """
        Generate Python code from annotated semiformal code.
        
        Single LLM call that generates:
        - Full Python code (always generates complete code, not diffs)
        - Backend handles diff computation
        
        Args:
            annotated_semiformal: Semiformal code annotated with parsed nodes
            existing_python: Existing Python code (for context)
            target_nodes: Optional list of target nodes that need generation
            generation_context: Context-aware information for better generation
            
        Returns:
            (generated_code, success)
        """
        
        messages = self._build_unified_prompt(
            annotated_semiformal=annotated_semiformal,
            existing_python=existing_python,
            target_nodes=target_nodes,
            trigger_type=trigger_type,
            previous_semiformal=previous_semiformal,
            generation_context=generation_context
        )
        
        max_retries = self.config.generator.max_llm_retries
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=messages,
                    response_format={ "type": "text"},
                    verbosity="medium",
                    reasoning_effort="minimal",
                    store=False,
                )
                
                generated = response.choices[0].message.content.strip()
                if not generated:
                    raise ValueError("LLM returned empty response")
                
                print(f"LLM response: {generated}")
                
                # Always extract code block (no diff mode)
                code = self._extract_code_block(generated)
                if code:
                    if self.config.generator.validate_generated_code:
                        validation_error = self._validate_python_code(code)
                        if validation_error:
                            raise ValueError(f"Generated code validation failed: {validation_error}")
                    return code, True
                
                raise ValueError("Could not extract code from LLM response")
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"LLM generation attempt {attempt + 1} failed: {str(e)}. Retrying...")
                    continue
                else:
                    print(f"LLM generation failed after {max_retries} attempts: {str(e)}")
        
        return "", False
    
    def _build_unified_prompt(
        self,
        annotated_semiformal: str,
        existing_python: str = "",
        target_nodes: List[Dict[str, Any]] = None,
        trigger_type: str = "initial",
        previous_semiformal: str = "",
        generation_context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, str]]:
        """Build messages list for LLM with system prompt, few-shot examples, and dynamic context"""
        
        messages = []
        
        # System message with static prompt
        messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT
        })
        
        # Add few-shot examples as assistant/user pairs
        messages.extend(_get_few_shot_examples())
        
        # Build dynamic user prompt
        prompt_parts = [
            "# Task: Generate Python Code from Semiformal Specification",
            "",
            f"**Trigger**: {trigger_type}",
        ]
        
        # Add dependency context if available (THIS IS KEY FOR DEPENDENT FUNCTIONS)
        if generation_context:
            prompt_parts.extend(_build_context_section(generation_context))
            
            # Check if any functions have been stripped for regeneration
            nodes_to_regenerate = generation_context.get('nodes_to_regenerate', [])
            if nodes_to_regenerate:
                prompt_parts.extend([
                    "",
                    "## CRITICAL: Function Body Regeneration",
                    "",
                    "**IMPORTANT**: Some functions in the semiformal specification below have their bodies replaced with `pass` statements.",
                    "This is INTENTIONAL. These functions require COMPLETE REGENERATION based on new context.",
                    "",
                    "For functions with `pass  # body omitted - will be regenerated`:",
                    "- DO NOT assume or copy from any prior implementation",
                    "- Generate FRESH, COMPLETE implementations from scratch",
                    "- Reason based on: function name, parameters, dependencies, and data flow context",
                    "- Consider what changed (data source, dependencies, signatures) and adapt accordingly",
                    "",
                ])
        
        # Show previous and current semiformal if editing
        if previous_semiformal:
            # Strip function bodies from previous semiformal too
            stripped_previous = previous_semiformal
            if generation_context and generation_context.get('functions_to_strip'):
                from generator import strip_function_bodies_for_regeneration
                functions_to_strip = set(generation_context['functions_to_strip'])
                stripped_previous = strip_function_bodies_for_regeneration(
                    semiformal_code=previous_semiformal,
                    functions_to_regenerate=functions_to_strip
                )
            
            prompt_parts.extend([
                "",
                "## Semiformal Specification (BEFORE)",
                "```",
                stripped_previous.strip(),
                "```",
            ])
        
        # Current semiformal specification
        prompt_parts.extend([
            "",
            "## Semiformal Specification (CURRENT, Annotated)",
            "```",
            annotated_semiformal.strip(),
            "```",
        ])
        
        # Existing Python code if updating
        if existing_python and existing_python.strip():
            prompt_parts.extend([
                "",
                "## Existing Python Code",
                "```python",
                existing_python.strip(),
                "```",
            ])
        
        # Add anchor rules reference
        prompt_parts.extend([
            "",
            ANCHOR_RULES,
        ])
        
        # Add target node focus if specified
        # if target_nodes:
        #     prompt_parts.extend([
        #         "",
        #         "## Focus Areas",
        #         f"Pay special attention to these {len(target_nodes)} node(s):",
        #     ])
        #     for node in target_nodes:
        #         node_type = node.get('type', 'unknown')
        #         value = node.get('value', '')
        #         prompt_parts.append(f"  - {node_type}: `{value}`")
        
        # Final instruction
        prompt_parts.extend([
            "",
            "## Your Task",
            "Generate the COMPLETE Python code (not a diff) following ALL anchor rules.",
            "Ensure every anchor from the semiformal spec appears in your code.",
            "If function signatures changed, update ALL callers and implementations.",
            "",
            "Output format:",
            "```python",
            "# Complete Python code here with inline anchor comments",
            "```",
        ])
        
        print('Built prompt for LLM:')
        print('\n'.join(prompt_parts))
        
        messages.append({
            "role": "user",
            "content": '\n'.join(prompt_parts)
        })
        
        return messages
    
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
        # Try to find diff in code block first (most reliable)
        # Handle ```diff ... ``` with optional newlines
        match = re.search(r'```\s*diff\s*\n(.*?)```', response, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Try generic ``` block that contains diff markers
        match = re.search(r'```\s*\n(.*?---.*?)\n?```', response, re.DOTALL)
        if match:
            content = match.group(1).strip()
            if '---' in content and '+++' in content:
                return content
        
        # Look for diff markers directly (not in code block)
        if '---' in response and '+++' in response:
            # Extract diff section
            lines = response.split('\n')
            diff_start = None
            for i, line in enumerate(lines):
                if line.startswith('---') or line.startswith('diff --git'):
                    diff_start = i
                    break
            
            if diff_start is not None:
                # Find end of diff (either end of string or start of new markdown block)
                diff_end = len(lines)
                for i in range(diff_start + 1, len(lines)):
                    if lines[i].strip().startswith('```'):
                        diff_end = i
                        break
                return '\n'.join(lines[diff_start:diff_end]).strip()
        
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

def _get_few_shot_examples() -> List[Dict[str, str]]:
    """Return few-shot examples as message pairs"""
    return [
        {
            "role": "user",
            "content": """# Task: Generate Python Code from Semiformal Specification

## Semiformal Specification (CURRENT, Annotated)
```
#> result; load; dataset
result = load the dataset

#> output; transform; result
output = transform(result)

#> print; output
print(output)
```

## Your Task
Generate the COMPLETE Python code following ALL anchor rules."""
        },
        {
            "role": "assistant",
            "content": """```python
import pandas as pd

data = pd.read_csv('data.csv')  #> load; dataset
result = data  #> result

output = result.apply(lambda x: x * 2)  #> output; transform; result

print(output)  #> print; output
```"""
        },
        {
            "role": "user",
            "content": """# Task: Generate Python Code from Semiformal Specification

## Semiformal Specification (CURRENT, Annotated)
```
#> result; preprocessing; data
result = preprocessing(data)
```

## Your Task
Generate the COMPLETE Python code including the preprocessing function implementation."""
        },
        {
            "role": "assistant",
            "content": """```python
import pandas as pd

def preprocessing(data):  #> preprocessing
    data = data.dropna()  #> drop na
    for col in data.columns:  #< coerce numeric
        if data[col].dtype == 'object':
            coerced = pd.to_numeric(data[col], errors='coerce')
            if coerced.notna().sum() > 0:
                data[col] = coerced
    return data

result = preprocessing(data)  #> result; preprocessing; data
```"""
        },
        {
            "role": "user",
            "content": """# Task: Generate Python Code from Semiformal Specification

**Trigger**: edit

## Dependency Graph Analysis

**Function Signature Changes Detected**:

IMPORTANT: The following function signatures have changed. You MUST:
1. Update ALL functions that CALL these functions to match new signatures
2. Update ALL function DEFINITIONS to reflect the new parameters
3. Update function implementations to use the new parameters correctly

- Function signature changed:
  - Old parameters: data
  - New parameters: data, threshold
  - Parameters ADDED: threshold

## Semiformal Specification (BEFORE)
```
#> clean_data
clean_data(data)
```

## Semiformal Specification (CURRENT, Annotated)
```
#> clean_data; threshold
clean_data(data, threshold)
```

## Existing Python Code
```python
import pandas as pd

def clean_data(data):  #> clean_data
    return data.dropna()

result = clean_data(df)  #> clean_data
```

## Your Task
Generate the COMPLETE Python code. Update the clean_data function definition to accept threshold parameter AND update the function body to use it."""
        },
        {
            "role": "assistant",
            "content": """```python
import pandas as pd

def clean_data(data, threshold):  #> clean_data; threshold
    data = data.dropna()
    data = data[data > threshold]
    return data

result = clean_data(df, threshold)  #> clean_data; threshold
```"""
        }
    ]



def _build_context_section(context: Dict[str, Any]) -> List[str]:
    """
    Build a generic context section from DAG analysis.
    
    This is completely generic - no hardcoded datasets or assumptions.
    Context is derived from the dependency graph structure.
    
    Args:
        context: Dictionary with:
            - changes: List of graph changes
            - nodes_to_regenerate: Node IDs that need regeneration
            - regeneration_order: Topological order
            - node_contexts: Dict of node_id -> context info
    """
    lines = [
        "",
        "## Dependency Graph Analysis",
        "",
    ]
    
    changes = context.get('changes', [])
    nodes_to_regenerate = context.get('nodes_to_regenerate', [])
    node_contexts = context.get('node_contexts', {})
    
    # Summarize what changed in the graph
    if changes:
        lines.append("**Detected Changes**:")
        
        change_types = {}
        signature_changes = []
        
        for change in changes:
            change_type = change.get('type', 'unknown')
            change_types[change_type] = change_types.get(change_type, 0) + 1
            
            # Track signature changes specifically
            metadata = change.get('metadata', {})
            if metadata.get('signature_changed'):
                signature_changes.append({
                    'node_id': change.get('node_id'),
                    'old_params': metadata.get('old_params', []),
                    'new_params': metadata.get('new_params', [])
                })
        
        for change_type, count in change_types.items():
            lines.append(f"- {count} {change_type.replace('_', ' ')} change(s)")
        
        # Highlight signature changes
        if signature_changes:
            lines.append("")
            lines.append("**Function Signature Changes Detected**:")
            lines.append("")
            lines.append("IMPORTANT: The following function signatures have changed. You MUST:")
            lines.append("1. Update ALL functions that CALL these functions to match new signatures")
            lines.append("2. Update ALL function DEFINITIONS to reflect the new parameters")
            lines.append("3. Update function implementations to use the new parameters correctly")
            lines.append("")
            
            for sig_change in signature_changes:
                old_params = sig_change['old_params']
                new_params = sig_change['new_params']
                lines.append(f"- Function signature changed:")
                lines.append(f"  - Old parameters: {', '.join(old_params) if old_params else '(none)'}")
                lines.append(f"  - New parameters: {', '.join(new_params) if new_params else '(none)'}")
                
                # Explain what changed
                added = set(new_params) - set(old_params)
                removed = set(old_params) - set(new_params)
                if added:
                    lines.append(f"  - Parameters ADDED: {', '.join(added)}")
                if removed:
                    lines.append(f"  - Parameters REMOVED: {', '.join(removed)}")
        
        lines.append("")
    
    # Explain what needs regeneration
    if nodes_to_regenerate:
        lines.append(f"**Nodes Requiring Regeneration**: {len(nodes_to_regenerate)} node(s)")
        lines.append("")
        lines.append("These nodes and their dependents need to be updated based on the changes:")
        
        # Group nodes by kind for clearer explanation
        nodes_by_kind = {}
        for node_id in nodes_to_regenerate[:10]:  # Limit to first 10 for brevity
            node_ctx = node_contexts.get(node_id, {})
            kind = node_ctx.get('kind', 'unknown')
            nodes_by_kind.setdefault(kind, []).append(node_id)
        
        for kind, node_ids in nodes_by_kind.items():
            lines.append(f"- {kind}: {len(node_ids)} node(s)")
        
        lines.append("")
    
    # Provide detailed context for key nodes
    if node_contexts:
        lines.append("**Node Dependencies & Context**:")
        lines.append("")
        lines.append("The following nodes have dependencies that inform their implementation:")
        lines.append("")
        
        # Show details for up to 5 most important nodes (those with most dependencies)
        sorted_nodes = sorted(
            node_contexts.items(),
            key=lambda x: len(x[1].get('dependencies', [])),
            reverse=True
        )[:5]
        
        for node_id, node_ctx in sorted_nodes:
            kind = node_ctx.get('kind', 'unknown')
            value = node_ctx.get('value', '')
            dependencies = node_ctx.get('dependencies', [])
            dependency_info = node_ctx.get('dependency_info', {})
            
            lines.append(f"- Node `{value}` ({kind}):")
            
            if dependencies:
                lines.append(f"  - Depends on {len(dependencies)} node(s):")
                for dep_id in dependencies[:3]:  # Show first 3 dependencies
                    dep_info = dependency_info.get(dep_id, {})
                    dep_value = dep_info.get('value', dep_id)
                    dep_kind = dep_info.get('kind', 'unknown')
                    dep_type = dep_info.get('type', 'inferred')
                    
                    type_info = f" (type: {dep_type})" if dep_type else ""
                    lines.append(f"    - `{dep_value}` ({dep_kind}){type_info}")
                
                if len(dependencies) > 3:
                    lines.append(f"    - ... and {len(dependencies) - 3} more")
            else:
                lines.append("  - No dependencies (leaf node)")
            
            # Add metadata hints if available
            metadata = node_ctx.get('metadata', {})
            if metadata:
                interesting_keys = {'full_statement', 'function_args', 'is_definition'}
                for key in interesting_keys:
                    if key in metadata:
                        lines.append(f"  - {key}: {metadata[key]}")
            
            lines.append("")
    
    lines.extend([
        "**Critical Generation Guidelines - Reason Like a Data Scientist**:",
        "",
        "1. **Identify the Root Change**: What exactly changed? (dataset name, parameter, function signature, etc.)",
        "",
        "2. **Trace Data Flow**: Follow the data flow from the changed node to all dependent nodes:",
        "   - What functions receive data from the changed source?",
        "   - What operations are performed on this data?",
        "   - How do dependent functions need to adapt?",
        "",
        "3. **Dataset-Specific Adaptations**: If data source changed (e.g., 'iris.csv' → 'titanic.csv'):",
        "   - Titanic: passenger data, survival prediction, demographics (Age, Sex, Pclass, Fare, Embarked)",
        "   - Iris: flower measurements, species classification (sepal/petal length/width)",
        "   - Generic: inspect dtypes, handle missing values, encode categoricals, scale numerics",
        "",
        "4. **Update ALL Affected Functions**: For each dependent function in the regeneration list:",
        "   - Update signatures if parameters changed",
        "   - Update implementation logic to handle new data characteristics",
        "   - Update ALL callers to pass correct arguments",
        "   - Ensure return values match what dependents expect",
        "",
        "5. **Maintain Code Quality**:",
        "   - Use pandas best practices for data manipulation",
        "   - Handle edge cases (missing data, type conversions)",
        "   - Keep operations efficient and idiomatic",
        "",
        "6. **Verify Completeness**: Ensure ALL nodes in the regeneration list are updated",
        "",
    ])
    
    return lines
