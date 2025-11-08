# MVP Architecture: Semiformal Programming with CodeMirror + OpenAI

This document outlines the simplified MVP approach focusing on **bidirectional semiformal programming** using CodeMirror for the editor and OpenAI API for code generation.

---

## Table of Contents

1. [Semiformal Language Specification](#1-semiformal-language-specification)
2. [Parser & Node Extraction](#2-parser--node-extraction)
3. [Code Generator with Mapping](#3-code-generator-with-mapping)
4. [Bidirectional Edit Translator](#4-bidirectional-edit-translator)
5. [Formal Update Rules](#5-formal-update-rules)
6. [MVP Demo Flow](#6-mvp-demo-flow)
7. [Example Walkthrough](#7-example-walkthrough)

---

## 1. Semiformal Language Specification

### EBNF Grammar

```ebnf
statement := python_stmt | nl_assignment | hole_stmt
python_stmt := <valid Python>
nl_assignment := identifier "=" nl_expression
hole_stmt := identifier "=" "{" "}" | identifier "=" "{" hint "}"
nl_expression := <any text that's not valid Python>
```

### Examples

```python
# Pure Python statement
result = process_data(raw_input)

# NL assignment (natural language)
x = split dataset into training and test

# Hole without hint (LLM fills completely)
y = {}

# Hole with hint (constrained LLM generation)
z = {use sklearn.preprocessing}
```

### Key Concepts

- **Python statements**: Valid Python code that can be parsed by AST
- **NL assignments**: Left-hand side is identifier(s), right-hand side is natural language
- **Holes**: Explicit markers `{}` for LLM to fill, optionally with hints
- **Hybrid mixing**: Can combine Python and NL in the same program

---

## 2. Parser & Node Extraction

### Core Data Structures

```python
from dataclasses import dataclass
from typing import List, Tuple, Optional
import ast

@dataclass
class IntentNode:
    """Represents a semantic unit in semiformal code"""
    id: str  # Unique node ID (e.g., "node_5_x", "node_7_nl_2")
    type: str  # 'identifier', 'operator', 'keyword', 'nl_phrase', 'python_expr'
    content: str  # The actual text content
    span: Tuple[int, int]  # Character span in semiformal code (start, end)
    dependencies: List[str]  # Node IDs this depends on

@dataclass
class CodeSlice:
    """Represents a slice of generated Python code"""
    code: str
    line_start: int
    line_end: int
    ast_nodes: List[ast.AST]  # Corresponding AST nodes

@dataclass
class Mapping:
    """Maps intent nodes to generated code slices"""
    node_id: str
    slices: List[CodeSlice]  # Can map to multiple code slices
    confidence: float  # 0.0 to 1.0
    generation_method: str  # 'direct', 'llm_generated', 'template'
```

### Parser Implementation

```python
class SemiformalParser:
    """Parse semiformal code into intent nodes"""

    def parse(self, code: str) -> List[IntentNode]:
        """Parse semiformal code into intent nodes"""
        nodes = []

        for line_num, line in enumerate(code.split('\n')):
            # Try parsing as Python first
            try:
                tree = ast.parse(line)
                # It's valid Python - tokenize it
                nodes.extend(self._tokenize_python_line(line, line_num))
            except SyntaxError:
                # It's NL or hybrid - parse specially
                nodes.extend(self._parse_nl_assignment(line, line_num))

        # Build dependency graph
        self._compute_dependencies(nodes)
        return nodes

    def _tokenize_python_line(self, line: str, line_num: int) -> List[IntentNode]:
        """
        Fine-grained tokenization of Python code.

        Example: "x = process_data(raw)" ->
        [
            Node(id='node_5_x', type='identifier', content='x'),
            Node(id='node_5_eq', type='operator', content='='),
            Node(id='node_5_process_data', type='function_call', content='process_data'),
            Node(id='node_5_raw', type='identifier', content='raw')
        ]
        """
        tokens = ast.parse(line).body[0]
        nodes = []

        if isinstance(tokens, ast.Assign):
            # Parse targets (LHS)
            for target in tokens.targets:
                nodes.append(IntentNode(
                    id=f"node_{line_num}_{ast.unparse(target)}",
                    type='identifier',
                    content=ast.unparse(target),
                    span=(line_num, line_num),
                    dependencies=[]
                ))

            # Parse value expression (RHS)
            value_nodes = self._tokenize_expr(tokens.value, line_num)
            nodes.extend(value_nodes)

        return nodes

    def _parse_nl_assignment(self, line: str, line_num: int) -> List[IntentNode]:
        """
        Parse NL assignments like 'x = split dataset into training'

        Returns:
        [
            Node(id='node_7_x', type='identifier', content='x'),
            Node(id='node_7_nl_0', type='nl_phrase', content='split'),
            Node(id='node_7_nl_1', type='nl_phrase', content='dataset'),
            Node(id='node_7_nl_2', type='nl_phrase', content='training')
        ]
        """
        if '=' not in line:
            return []  # Pure NL comment or directive

        lhs, rhs = line.split('=', 1)
        lhs = lhs.strip()
        rhs = rhs.strip()

        nodes = []

        # Parse LHS (target identifiers)
        targets = [t.strip() for t in lhs.split(',')]
        for target in targets:
            nodes.append(IntentNode(
                id=f"node_{line_num}_{target}",
                type='identifier',
                content=target,
                span=(line_num, line_num),
                dependencies=[]
            ))

        # Check if RHS is a hole
        if rhs.startswith('{') and rhs.endswith('}'):
            hint = rhs[1:-1].strip()
            nodes.append(IntentNode(
                id=f"node_{line_num}_hole",
                type='hole',
                content=hint if hint else '',
                span=(line_num, line_num),
                dependencies=[]
            ))
        else:
            # Parse RHS as NL expression
            nl_tokens = self._segment_nl_phrase(rhs)
            for i, token in enumerate(nl_tokens):
                nodes.append(IntentNode(
                    id=f"node_{line_num}_nl_{i}",
                    type='nl_phrase',
                    content=token,
                    span=(line_num, line_num),
                    dependencies=[]
                ))

        return nodes

    def _segment_nl_phrase(self, phrase: str) -> List[str]:
        """
        Segment NL phrase into semantic units.

        Example: "split dataset into training and test sets"
        Returns: ["split", "dataset", "training", "test sets"]

        In production: use spaCy or dependency parsing for better segmentation.
        """
        keywords = ['split', 'load', 'transform', 'train', 'test',
                   'dataset', 'model', 'data', 'into', 'from', 'using']

        tokens = []
        words = phrase.split()

        i = 0
        while i < len(words):
            if words[i] in keywords:
                # Check if next words form a compound phrase
                chunk = words[i]
                j = i + 1
                while j < len(words) and words[j] not in keywords:
                    chunk += " " + words[j]
                    j += 1
                tokens.append(chunk)
                i = j
            else:
                i += 1

        return tokens

    def _compute_dependencies(self, nodes: List[IntentNode]):
        """Build dependency graph between nodes"""
        # Simple implementation: identifiers depend on previous definitions
        defined_vars = set()

        for node in nodes:
            if node.type == 'identifier':
                if node.content in defined_vars:
                    # This identifier uses a previously defined variable
                    # Find the definition node
                    for prev_node in nodes:
                        if prev_node.content == node.content and prev_node != node:
                            node.dependencies.append(prev_node.id)
                            break
                else:
                    defined_vars.add(node.content)
```

---

## 3. Code Generator with Mapping

### Generator Implementation

```python
class CodeGenerator:
    """Generate Python code from intent nodes and create mappings"""

    def __init__(self, openai_api_key: str):
        import openai
        self.client = openai.OpenAI(api_key=openai_api_key)

    def generate_with_mapping(
        self,
        nodes: List[IntentNode],
        context: str
    ) -> Tuple[str, List[Mapping]]:
        """
        Generate Python code and create node→code mappings.

        Returns:
            (generated_code, mappings)
        """
        # Group nodes by statement
        statements = self._group_into_statements(nodes)

        generated_lines = []
        mappings = []

        for stmt_nodes in statements:
            if self._is_pure_python(stmt_nodes):
                # Direct translation (no LLM needed)
                code = self._reconstruct_python(stmt_nodes)
                generated_lines.append(code)

                # Create 1:1 mapping
                for node in stmt_nodes:
                    mappings.append(Mapping(
                        node_id=node.id,
                        slices=[CodeSlice(
                            code=code,
                            line_start=len(generated_lines),
                            line_end=len(generated_lines),
                            ast_nodes=[ast.parse(code).body[0]]
                        )],
                        confidence=1.0,
                        generation_method='direct'
                    ))
            else:
                # LLM generation needed
                code, node_mappings = self._generate_with_llm(
                    stmt_nodes, context, len(generated_lines)
                )
                generated_lines.extend(code.split('\n'))
                mappings.extend(node_mappings)

        return '\n'.join(generated_lines), mappings

    def _is_pure_python(self, nodes: List[IntentNode]) -> bool:
        """Check if all nodes are valid Python (no NL or holes)"""
        for node in nodes:
            if node.type in ('nl_phrase', 'hole'):
                return False
        return True

    def _reconstruct_python(self, nodes: List[IntentNode]) -> str:
        """Reconstruct Python code from nodes"""
        # Simple concatenation for now
        return ' '.join(node.content for node in nodes)

    def _generate_with_llm(
        self,
        nodes: List[IntentNode],
        context: str,
        start_line: int
    ) -> Tuple[str, List[Mapping]]:
        """
        Use LLM to generate code for NL/hole nodes.

        Prompt includes special annotations to track which nodes
        map to which generated code lines.
        """
        # Extract the intent
        identifiers = [n for n in nodes if n.type == 'identifier']
        nl_phrases = [n for n in nodes if n.type == 'nl_phrase']
        holes = [n for n in nodes if n.type == 'hole']

        # Build prompt
        if holes:
            intent_description = f"Fill hole with hint: {holes[0].content}"
        else:
            intent_description = ' '.join([n.content for n in nl_phrases])

        prompt = f"""
Generate Python code for this intent:

Assignment targets: {[n.content for n in identifiers]}
Intent: {intent_description}

Context:
{context}

Requirements:
1. Return ONLY valid Python code
2. Use common libraries (pandas, sklearn, numpy)
3. Code should assign to: {', '.join([n.content for n in identifiers])}
4. Annotate each line with [NODE:node_id1,node_id2] to indicate which intent nodes it implements

Format:
```python
# [NODE:node_id1,node_id2]
generated_code_line_1
# [NODE:node_id3]
generated_code_line_2
```
"""

        # Call OpenAI API
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Python code generator."},
                {"role": "user", "content": prompt}
            ]
        )

        code = self._extract_code_block(response.choices[0].message.content)

        # Parse the annotations to create mappings
        mappings = self._parse_node_annotations(code, nodes, start_line)

        return code, mappings

    def _extract_code_block(self, response: str) -> str:
        """Extract code from markdown code block"""
        import re
        match = re.search(r'```python\n(.*?)\n```', response, re.DOTALL)
        if match:
            return match.group(1)
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

        Creates mappings:
        - node_5_x -> line 5
        - node_5_split -> line 5
        """
        import re
        mappings = []
        lines = code.split('\n')

        for i, line in enumerate(lines):
            # Look for [NODE:...] annotation
            match = re.search(r'# \[NODE:(.*?)\]', line)
            if match:
                node_ids = match.group(1).split(',')
                for node_id in node_ids:
                    node_id = node_id.strip()
                    # Find the corresponding node
                    node = next((n for n in nodes if n.id == node_id), None)
                    if node:
                        # Remove annotation from code
                        clean_line = re.sub(r'# \[NODE:.*?\]', '', lines[i + 1] if i + 1 < len(lines) else line).strip()

                        mappings.append(Mapping(
                            node_id=node_id,
                            slices=[CodeSlice(
                                code=clean_line,
                                line_start=start_line + i + 1,
                                line_end=start_line + i + 1,
                                ast_nodes=[]
                            )],
                            confidence=0.85,  # LLM-generated
                            generation_method='llm_generated'
                        ))

        return mappings
```

---

## 4. Bidirectional Edit Translator

### Edit Data Structures

```python
@dataclass
class Edit:
    """Represents an edit to code"""
    type: str  # See EDIT_MAPPING_TABLE.md for all types
    location: str  # Function name, line number, or node ID
    content: str  # The new content
    node_id: Optional[str] = None
    line: Optional[int] = None

@dataclass
class PythonEdit:
    """Edit to apply to Python code"""
    type: str  # 'replace', 'insert', 'delete'
    line_start: int
    line_end: int
    new_code: str
    confidence: float
    affects_mappings: bool = False

    def apply(self, code: str) -> str:
        """Apply this edit to code"""
        lines = code.split('\n')
        if self.type == 'replace':
            lines[self.line_start:self.line_end] = [self.new_code]
        elif self.type == 'insert':
            lines.insert(self.line_start, self.new_code)
        elif self.type == 'delete':
            del lines[self.line_start:self.line_end]
        return '\n'.join(lines)

@dataclass
class SemiformalEdit:
    """Edit to apply to semiformal code"""
    type: str  # 'replace', 'suggest', 'no_change'
    description: str = ""
    suggested_change: str = ""
    confidence: float = 1.0
```

### Edit Translator Implementation

```python
class EditTranslator:
    """Translate edits between semiformal and Python"""

    def __init__(self, mappings: List[Mapping], openai_api_key: str):
        self.mappings = {m.node_id: m for m in mappings}
        import openai
        self.client = openai.OpenAI(api_key=openai_api_key)

    def semiformal_to_python(
        self,
        edit: Edit,
        semiformal_code: str,
        python_code: str
    ) -> PythonEdit:
        """Translate semiformal edit to Python edit"""

        # Classify edit type (see EDIT_MAPPING_TABLE.md)
        if self._is_direct_translatable(edit):
            return self._direct_translate(edit)
        elif self._is_hole_fill(edit):
            return self._fill_hole(edit)
        elif self._needs_llm(edit):
            return self._llm_translate(edit, semiformal_code, python_code)
        else:
            return self._incremental_regen(edit, python_code)

    def _is_direct_translatable(self, edit: Edit) -> bool:
        """
        Check if edit can be directly mapped to Python.

        Direct translatable edits (36.6% from EDIT_MAPPING_TABLE.md):
        - identifier renames
        - operator changes
        - literal changes
        - argument reordering
        """
        direct_types = [
            'identifier_rename',
            'operator_change',
            'literal_change',
            'identifier_add',
            'param_rename',
            'param_reorder',
        ]
        return edit.type in direct_types

    def _direct_translate(self, edit: Edit) -> PythonEdit:
        """
        Directly translate edit to Python using AST manipulation.

        Example: x = ... -> x, y = ...
        Becomes: x = value -> x, y = value, None
        """
        if edit.type == 'identifier_add':
            # Example from EDIT_MAPPING_TABLE.md
            node_id = edit.node_id
            mapping = self.mappings[node_id]

            # Find the assignment statement
            for slice in mapping.slices:
                tree = ast.parse(slice.code)
                assign = tree.body[0]

                if isinstance(assign, ast.Assign):
                    # Modify the targets
                    new_targets = assign.targets[0]
                    if isinstance(new_targets, ast.Name):
                        # Single target -> make it a tuple
                        new_targets = ast.Tuple(
                            elts=[
                                new_targets,
                                ast.Name(id=edit.content, ctx=ast.Store())
                            ],
                            ctx=ast.Store()
                        )
                    elif isinstance(new_targets, ast.Tuple):
                        # Already a tuple -> add to it
                        new_targets.elts.append(
                            ast.Name(id=edit.content, ctx=ast.Store())
                        )

                    assign.targets[0] = new_targets
                    new_code = ast.unparse(tree)

                    return PythonEdit(
                        type='replace',
                        line_start=slice.line_start,
                        line_end=slice.line_end,
                        new_code=new_code,
                        confidence=1.0,
                        affects_mappings=True
                    )

        elif edit.type == 'identifier_rename':
            # Use AST to rename all occurrences
            # ... (similar AST manipulation)
            pass

        # Default
        return PythonEdit(
            type='replace',
            line_start=0,
            line_end=0,
            new_code='',
            confidence=0.0
        )

    def _is_hole_fill(self, edit: Edit) -> bool:
        """Check if this is filling a hole"""
        return edit.type == 'hole_fill'

    def _fill_hole(self, edit: Edit) -> PythonEdit:
        """Fill a hole using LLM with hint"""
        # Similar to _generate_with_llm in CodeGenerator
        pass

    def _needs_llm(self, edit: Edit) -> bool:
        """Check if edit needs LLM for translation"""
        llm_types = [
            'nl_phrase_add',
            'nl_phrase_modify',
            'add_function',
            'semantic_change'
        ]
        return edit.type in llm_types

    def _llm_translate(self, edit: Edit, semiformal_code: str, python_code: str) -> PythonEdit:
        """Use LLM to translate complex edits"""
        # Call OpenAI API to interpret the edit
        pass

    def python_to_semiformal(
        self,
        python_edit: PythonEdit,
        python_code: str,
        semiformal_code: str
    ) -> SemiformalEdit:
        """
        Translate Python edit back to semiformal.

        Uses the decision tree from EDIT_MAPPING_TABLE.md:
        1. Check if in generated region (transient)
        2. Check if refactoring (don't propagate)
        3. Check if semantic change (propagate)
        """
        # Step 1: Detect what semantically changed
        old_ast = ast.parse(python_code)
        new_ast = ast.parse(python_edit.apply(python_code))

        semantic_diff = self._compute_semantic_diff(old_ast, new_ast)

        # Step 2: Check if change is "within spec"
        if self._is_within_transient_region(python_edit):
            # It's in the generated region - don't propagate
            return SemiformalEdit(type='no_change')

        # Step 3: Use LLM to summarize the change
        summary = self._llm_summarize_change(
            old_code=python_code[python_edit.line_start:python_edit.line_end],
            new_code=python_edit.new_code,
            context=semiformal_code
        )

        # Step 4: Surface to user
        return SemiformalEdit(
            type='suggest',
            description=summary,
            suggested_change=self._generate_semiformal_update(summary),
            confidence=0.7
        )

    def _is_within_transient_region(self, python_edit: PythonEdit) -> bool:
        """
        Check if edit is in a generated region (transient).

        From EDIT_MAPPING_TABLE.md Part 2, Section M:
        - Tweaking constants: transient
        - Changing library calls: may be transient
        - Bug fixes: transient
        """
        for mapping in self.mappings.values():
            for slice in mapping.slices:
                if slice.line_start <= python_edit.line_start <= slice.line_end:
                    # Check if it was LLM-generated
                    if mapping.generation_method == 'llm_generated':
                        return True
        return False

    def _compute_semantic_diff(self, old_ast: ast.AST, new_ast: ast.AST) -> dict:
        """Compute semantic difference between two ASTs"""
        # Compare function definitions, imports, etc.
        return {}

    def _llm_summarize_change(self, old_code: str, new_code: str, context: str) -> str:
        """Use LLM to summarize a code change in natural language"""
        prompt = f"""
Summarize this code change in natural language:

Before:
{old_code}

After:
{new_code}

Context:
{context}

Provide a brief 1-2 sentence summary of what changed semantically.
"""
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a code change analyzer."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content

    def _generate_semiformal_update(self, summary: str) -> str:
        """Generate semiformal code update from summary"""
        # Convert summary to semiformal syntax
        # e.g., "Added data validation" -> "validated = validate data"
        return summary
```

---

## 5. Formal Update Rules

### Update Rule System

```python
@dataclass
class UpdateRule:
    """Defines when and how updates propagate"""
    trigger: str  # What kind of edit triggers this
    propagation: str  # 'required', 'optional', 'forbidden'
    direction: str  # 'semiformal->python', 'python->semiformal', 'both'
    strategy: str  # 'direct', 'llm', 'template', 'regenerate'

# From EDIT_MAPPING_TABLE.md
UPDATE_RULES = [
    # Semiformal -> Python rules
    UpdateRule(
        trigger='identifier_change_lhs',
        propagation='required',
        direction='semiformal->python',
        strategy='direct'
    ),
    UpdateRule(
        trigger='nl_phrase_add',
        propagation='required',
        direction='semiformal->python',
        strategy='llm'
    ),
    UpdateRule(
        trigger='nl_phrase_modify',
        propagation='required',
        direction='semiformal->python',
        strategy='regenerate'
    ),
    UpdateRule(
        trigger='python_expr_add',
        propagation='required',
        direction='semiformal->python',
        strategy='direct'
    ),

    # Python -> Semiformal rules
    UpdateRule(
        trigger='semantic_change_in_generated_region',
        propagation='optional',
        direction='python->semiformal',
        strategy='llm'
    ),
    UpdateRule(
        trigger='refactoring',
        propagation='forbidden',
        direction='python->semiformal',
        strategy='none'
    ),
    UpdateRule(
        trigger='new_function_added',
        propagation='required',
        direction='python->semiformal',
        strategy='llm'
    ),
]

class UpdateDecider:
    """Decide if and how edits should propagate"""

    def __init__(self, rules: List[UpdateRule]):
        self.rules = rules

    def should_propagate(self, edit: Edit) -> Tuple[bool, str]:
        """
        Decide if an edit should propagate and how.

        Returns:
            (should_propagate, strategy)
        """
        # Find matching rule
        rule = self._find_matching_rule(edit)

        if rule.propagation == 'required':
            return True, rule.strategy
        elif rule.propagation == 'optional':
            # Ask user or use heuristic
            if self._is_significant_change(edit):
                return True, rule.strategy
            return False, 'none'
        else:  # forbidden
            return False, 'none'

    def _find_matching_rule(self, edit: Edit) -> UpdateRule:
        """Find the first matching rule for this edit"""
        for rule in self.rules:
            if self._matches_trigger(edit, rule.trigger):
                return rule
        # Default rule: optional LLM
        return UpdateRule('default', 'optional', 'both', 'llm')

    def _matches_trigger(self, edit: Edit, trigger: str) -> bool:
        """Check if edit matches trigger pattern"""
        # Simple string matching for now
        return edit.type == trigger or trigger in edit.type

    def _is_significant_change(self, edit: Edit) -> bool:
        """Heuristic to determine if change is significant"""
        # Consider change significant if:
        # - Adds new function
        # - Changes > 5 lines
        # - Modifies public API
        return True  # Simplified
```

---

## 6. MVP Demo Flow

### Main Editor Class

```python
class BidirectionalEditor:
    """Main editor orchestrating semiformal ↔ Python synchronization"""

    def __init__(self, openai_api_key: str):
        self.parser = SemiformalParser()
        self.generator = CodeGenerator(openai_api_key)
        self.translator = EditTranslator([], openai_api_key)
        self.update_decider = UpdateDecider(UPDATE_RULES)

        self.semiformal_code = ""
        self.python_code = ""
        self.intent_nodes = []
        self.mappings = []

    def initialize(self, semiformal_code: str) -> str:
        """
        Initialize from semiformal code.

        Flow:
        1. Parse semiformal -> intent nodes
        2. Generate Python from nodes
        3. Create node→code mappings
        4. Set up translator

        Returns:
            Generated Python code
        """
        # Parse
        self.semiformal_code = semiformal_code
        self.intent_nodes = self.parser.parse(semiformal_code)

        # Generate Python
        self.python_code, self.mappings = self.generator.generate_with_mapping(
            self.intent_nodes,
            context=semiformal_code
        )

        # Create translator with mappings
        self.translator = EditTranslator(self.mappings, self.generator.client.api_key)

        return self.python_code

    def on_semiformal_edit(self, edit: Edit):
        """
        User edited the semiformal spec.

        Flow:
        1. Translate semiformal edit -> Python edit
        2. Apply Python edit
        3. Update mappings if needed
        """
        # Translate to Python edit
        python_edit = self.translator.semiformal_to_python(
            edit,
            self.semiformal_code,
            self.python_code
        )

        # Apply
        self.python_code = python_edit.apply(self.python_code)

        # Update mappings if needed
        if python_edit.affects_mappings:
            self._recompute_mappings(edit)

    def on_python_edit(self, python_edit: PythonEdit):
        """
        User edited the generated Python.

        Flow:
        1. Decide if should propagate (using UpdateDecider)
        2. If transient: just update Python
        3. If semantic: translate back to semiformal
        4. Surface suggestion to user
        """
        # Decide if should propagate
        should_prop, strategy = self.update_decider.should_propagate(
            Edit(type='python_change', location='', content=python_edit.new_code)
        )

        if not should_prop:
            # Transient change - just update Python
            self.python_code = python_edit.apply(self.python_code)
            return

        # Translate back to semiformal
        semiformal_edit = self.translator.python_to_semiformal(
            python_edit,
            self.python_code,
            self.semiformal_code
        )

        # Surface to user
        if semiformal_edit.type == 'suggest':
            # Show suggestion UI
            self._show_suggestion(semiformal_edit)

    def _recompute_mappings(self, edit: Edit):
        """Recompute mappings after an edit that affects structure"""
        # Re-parse and re-generate mappings
        self.intent_nodes = self.parser.parse(self.semiformal_code)
        # Regenerate only affected parts
        pass

    def _show_suggestion(self, semiformal_edit: SemiformalEdit):
        """Show suggestion to user (UI integration point)"""
        print(f"Python change detected: {semiformal_edit.description}")
        print(f"Suggested semiformal update: {semiformal_edit.suggested_change}")
        # User can accept/reject
```

---

## 7. Example Walkthrough

### Initial Semiformal Code

```python
result = process_data(raw_input)
x = split dataset into training and test sets
output = transform(x)
print(result, x, output)
```

### Step 1: Parsing

```python
parser = SemiformalParser()
nodes = parser.parse(semiformal_code)

# Result:
nodes = [
    Node(id='node_0_result', type='identifier', content='result'),
    Node(id='node_0_process_data', type='function_call', content='process_data'),
    Node(id='node_1_x', type='identifier', content='x'),
    Node(id='node_1_nl_0', type='nl_phrase', content='split dataset'),
    Node(id='node_1_nl_1', type='nl_phrase', content='training and test sets'),
    Node(id='node_2_output', type='identifier', content='output'),
    Node(id='node_2_transform', type='function_call', content='transform'),
    # ... more nodes
]
```

### Step 2: Generation

```python
generator = CodeGenerator(openai_api_key)
python_code, mappings = generator.generate_with_mapping(nodes, semiformal_code)

# Generated Python:
"""
result = process_data(raw_input)

# [NODE:node_1_x,node_1_nl_0,node_1_nl_1]
from sklearn.model_selection import train_test_split
X_train, X_test = train_test_split(dataset, test_size=0.2)
x = {'train': X_train, 'test': X_test}

output = transform(x)
print(result, x, output)
"""

# Mappings:
mappings = [
    Mapping(node_id='node_1_x', slices=[...], generation_method='llm_generated'),
    Mapping(node_id='node_1_nl_0', slices=[...], generation_method='llm_generated'),
    # ...
]
```

### Step 3: User Edit - Add Variable to LHS

**Semiformal edit:**
```python
x = ...  →  x, y = ...
```

**Translation:**
```python
translator = EditTranslator(mappings, openai_api_key)
edit = Edit(type='identifier_add', node_id='node_1_x', content='y')
python_edit = translator.semiformal_to_python(edit, semiformal_code, python_code)

# Result: Direct translation + placeholder
"""
x, y = {'train': X_train, 'test': X_test}, None  # Need to determine y
"""
# Then LLM regenerates:
"""
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
x = {'train': X_train, 'test': X_test}
y = {'train': y_train, 'test': y_test}
"""
```

### Step 4: User Edit in Python (Transient)

**Python edit:**
```python
# User changes
test_size=0.2  →  test_size=0.3
```

**Decision:**
```python
update_decider = UpdateDecider(UPDATE_RULES)
should_prop, strategy = update_decider.should_propagate(edit)
# Result: should_prop = False (transient parameter tuning)

# Semiformal code remains unchanged
```

### Step 5: User Edit in Python (Semantic)

**Python edit:**
```python
# User adds
def validate_data(data):
    return data[data > 0]

result = validate_data(process_data(raw_input))
```

**Translation:**
```python
python_edit = PythonEdit(...)
semiformal_edit = translator.python_to_semiformal(python_edit, python_code, semiformal_code)

# LLM summarizes: "Added data validation step"
# Suggested semiformal update:
"""
validated = remove negative values from data
result = process_data(validated)
"""
```

---

## Implementation Checklist

Based on EDIT_MAPPING_TABLE.md:

### Phase 1: Direct Edits (36.6% coverage)
- [ ] AST-based renaming (variables, functions, parameters)
- [ ] Operator changes
- [ ] Literal value changes
- [ ] Argument reordering
- [ ] Simple statement insertion/deletion

### Phase 2: Placeholder Support (18.3%)
- [ ] Placeholder system for unknown values
- [ ] Stub generation for new identifiers
- [ ] User prompts for placeholder values

### Phase 3: Hole Syntax (14.1%)
- [ ] Define hole syntax: `{}` and `{hint}`
- [ ] Integrate holes with LLM generation
- [ ] Track hole locations

### Phase 4: LLM Integration (21.1%)
- [ ] OpenAI API integration
- [ ] Prompt templates for each edit type
- [ ] LLM result parser
- [ ] Confidence scoring

### Phase 5: Regeneration Logic (9.9%)
- [ ] Detect when regeneration needed
- [ ] Track function/block boundaries
- [ ] Preserve user edits during regeneration

### Phase 6: Bidirectional Sync
- [ ] Python → Semiformal summarization
- [ ] Transient vs semantic classifier
- [ ] Suggestion UI for propagation
- [ ] User approval workflow

---

## Frontend Integration (CodeMirror)

### CodeMirror Setup

```typescript
// frontend/src/editor.ts
import { EditorView, basicSetup } from 'codemirror';
import { python } from '@codemirror/lang-python';
import { ViewUpdate } from '@codemirror/view';

class SemiformalEditor {
  private semiformalView: EditorView;
  private pythonView: EditorView;
  private backend: BidirectionalEditor;

  constructor(semiformalEl: HTMLElement, pythonEl: HTMLElement) {
    // Initialize semiformal editor
    this.semiformalView = new EditorView({
      doc: '',
      extensions: [
        basicSetup,
        python(),
        EditorView.updateListener.of((update: ViewUpdate) => {
          if (update.docChanged) {
            this.onSemiformalChange(update);
          }
        })
      ],
      parent: semiformalEl
    });

    // Initialize Python editor
    this.pythonView = new EditorView({
      doc: '',
      extensions: [
        basicSetup,
        python(),
        EditorView.updateListener.of((update: ViewUpdate) => {
          if (update.docChanged) {
            this.onPythonChange(update);
          }
        })
      ],
      parent: pythonEl
    });
  }

  async onSemiformalChange(update: ViewUpdate) {
    // Send edit to backend
    const edit = this.detectEdit(update);
    const response = await fetch('/api/semiformal-edit', {
      method: 'POST',
      body: JSON.stringify({ edit, code: this.semiformalView.state.doc.toString() })
    });
    const { pythonCode } = await response.json();
    this.pythonView.dispatch({
      changes: { from: 0, to: this.pythonView.state.doc.length, insert: pythonCode }
    });
  }

  async onPythonChange(update: ViewUpdate) {
    // Send edit to backend
    const pythonEdit = this.detectEdit(update);
    const response = await fetch('/api/python-edit', {
      method: 'POST',
      body: JSON.stringify({ edit: pythonEdit, code: this.pythonView.state.doc.toString() })
    });
    const { semiformalEdit } = await response.json();

    if (semiformalEdit.type === 'suggest') {
      this.showSuggestion(semiformalEdit);
    }
  }

  detectEdit(update: ViewUpdate): Edit {
    // Analyze update.changes to determine edit type
    // ...
    return { type: 'identifier_rename', location: '', content: '' };
  }

  showSuggestion(edit: SemiformalEdit) {
    // Show UI suggestion
    const accept = confirm(`Suggestion: ${edit.description}\n${edit.suggested_change}\nAccept?`);
    if (accept) {
      this.semiformalView.dispatch({
        changes: { from: 0, to: this.semiformalView.state.doc.length, insert: edit.suggested_change }
      });
    }
  }
}
```

---

## API Endpoints

### Backend Routes (FastAPI)

```python
# backend/main.py
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
editor = BidirectionalEditor(openai_api_key=os.getenv('OPENAI_API_KEY'))

class SemiformalEditRequest(BaseModel):
    edit: dict
    code: str

class PythonEditRequest(BaseModel):
    edit: dict
    code: str

@app.post('/api/initialize')
async def initialize(request: dict):
    semiformal_code = request['code']
    python_code = editor.initialize(semiformal_code)
    return {'pythonCode': python_code}

@app.post('/api/semiformal-edit')
async def semiformal_edit(request: SemiformalEditRequest):
    edit = Edit(**request.edit)
    editor.on_semiformal_edit(edit)
    return {'pythonCode': editor.python_code}

@app.post('/api/python-edit')
async def python_edit(request: PythonEditRequest):
    python_edit = PythonEdit(**request.edit)
    editor.on_python_edit(python_edit)
    # Return suggestion if any
    return {'semiformalEdit': {...}}
```

---

## Summary

This MVP architecture provides:

1. **Clear semiformal language spec** with Python, NL, and holes
2. **Fine-grained parsing** into intent nodes with dependencies
3. **Mapped generation** tracking nodes → code slices
4. **Bidirectional translation** with decision trees
5. **Formal update rules** for propagation logic
6. **CodeMirror integration** for real-time editing
7. **OpenAI API integration** for LLM generation

The system handles **71 semiformal → Python edit types** (see EDIT_MAPPING_TABLE.md), with 36.6% using direct AST manipulation, requiring no LLM calls.
