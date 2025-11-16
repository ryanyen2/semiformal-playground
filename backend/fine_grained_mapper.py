"""
Fine-Grained AST Mapping

Maps IntentNodes to specific AST nodes with column-level precision.
Handles NL phrases by mapping to their corresponding code fragments.
"""

import ast
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ASTMapping:
    """Fine-grained mapping to specific AST node"""
    node_id: str
    ast_node: ast.AST
    line: int
    col_start: int
    col_end: int
    code_text: str
    confidence: float
    mapping_type: str  # 'exact', 'semantic', 'inferred'


class FineGrainedMapper:
    """Maps IntentNodes to specific AST nodes (not entire lines)"""

    def __init__(self, generated_code: str):
        self.code = generated_code
        self.code_lines = generated_code.split('\n')
        try:
            self.ast_tree = ast.parse(generated_code)
        except SyntaxError:
            self.ast_tree = None

        # Build indices
        self.name_nodes: List[Tuple[ast.Name, int, int, int]] = []  # (node, line, col_start, col_end)
        self.call_nodes: List[Tuple[ast.Call, int, int, int]] = []
        self.assign_nodes: List[Tuple[ast.Assign, int]] = []
        self.function_def_nodes: List[Tuple[ast.FunctionDef, int]] = []
        self.import_nodes: List[Tuple[ast.AST, int]] = []  # Import or ImportFrom
        self.constant_nodes: List[Tuple[ast.Constant, int, int, int]] = []  # literals
        self.binop_nodes: List[Tuple[ast.BinOp, int, int, int]] = []  # binary operators

        if self.ast_tree:
            self._build_indices()

    def _build_indices(self):
        """Build indices of all AST nodes"""
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.Name):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start + len(node.id))
                self.name_nodes.append((node, line, col_start, col_end))

            elif isinstance(node, ast.Call):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start)
                self.call_nodes.append((node, line, col_start, col_end))

            elif isinstance(node, ast.Assign):
                line = getattr(node, 'lineno', 0)
                self.assign_nodes.append((node, line))

            elif isinstance(node, ast.FunctionDef):
                line = getattr(node, 'lineno', 0)
                self.function_def_nodes.append((node, line))

            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                line = getattr(node, 'lineno', 0)
                self.import_nodes.append((node, line))

            elif isinstance(node, ast.Constant):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start)
                self.constant_nodes.append((node, line, col_start, col_end))

            elif isinstance(node, ast.BinOp):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start)
                self.binop_nodes.append((node, line, col_start, col_end))

    def map_identifier(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """
        Map identifier to specific Name AST node.

        For definition (is_definition=True): maps to target
        For reference: maps to the Name node being referenced
        """
        name = intent_node.content
        is_definition = intent_node.metadata.get('is_definition', False)
        role = intent_node.metadata.get('role', '')

        if is_definition or role == 'target':
            # Find assignment where this is the target
            for assign_node, line in self.assign_nodes:
                for target in assign_node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        # This is the assignment target
                        col_start = getattr(target, 'col_offset', 0)
                        col_end = getattr(target, 'end_col_offset', col_start + len(name))
                        code_text = self._extract_text(line, col_start, col_end)

                        return ASTMapping(
                            node_id=intent_node.id,
                            ast_node=target,
                            line=line,
                            col_start=col_start,
                            col_end=col_end,
                            code_text=code_text,
                            confidence=0.95,
                            mapping_type='exact'
                        )

                    # Handle tuple unpacking: x, y = ...
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name) and elt.id == name:
                                col_start = getattr(elt, 'col_offset', 0)
                                col_end = getattr(elt, 'end_col_offset', col_start + len(name))
                                code_text = self._extract_text(line, col_start, col_end)

                                return ASTMapping(
                                    node_id=intent_node.id,
                                    ast_node=elt,
                                    line=line,
                                    col_start=col_start,
                                    col_end=col_end,
                                    code_text=code_text,
                                    confidence=0.95,
                                    mapping_type='exact'
                                )
        else:
            # Reference - find Name node being used (not assigned)
            candidates = []
            for name_node, line, col_start, col_end in self.name_nodes:
                if name_node.id == name and isinstance(name_node.ctx, ast.Load):
                    # This is a reference (Load context)
                    score = 100

                    # Strongly prefer main code (avoid function bodies)
                    if line >= 15:  # Heuristic: main code starts after function defs
                        score += 50
                    else:
                        score -= 50  # Penalize early lines (likely function bodies)

                    # CRITICAL: Strongly prefer matches closer to expected line
                    # This prevents all references from mapping to first occurrence
                    if expected_line:
                        distance = abs(line - expected_line)
                        score -= distance * 20  # Much stronger weight (was *2, now *20)

                    candidates.append((score, name_node, line, col_start, col_end))

            if candidates:
                # Pick best match
                candidates.sort(reverse=True, key=lambda x: x[0])
                _, name_node, line, col_start, col_end = candidates[0]

                code_text = self._extract_text(line, col_start, col_end)

                return ASTMapping(
                    node_id=intent_node.id,
                    ast_node=name_node,
                    line=line,
                    col_start=col_start,
                    col_end=col_end,
                    code_text=code_text,
                    confidence=0.9,
                    mapping_type='exact'
                )

        return None

    def map_function_call(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map function call to specific Call AST node"""
        func_name = intent_node.content

        candidates = []
        for call_node, line, col_start, col_end in self.call_nodes:
            # Check if this call matches the function name
            if isinstance(call_node.func, ast.Name) and call_node.func.id == func_name:
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance

                # Avoid function definitions (prefer call sites)
                if line < 10:  # Heuristic: early lines likely defs
                    score -= 20

                candidates.append((score, call_node, line, col_start, col_end))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, call_node, line, col_start, col_end = candidates[0]

            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=intent_node.id,
                ast_node=call_node,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.9,
                mapping_type='exact'
            )

        return None

    def map_nl_phrase(
        self,
        intent_node,
        sibling_mappings: List[ASTMapping]
    ) -> Optional[ASTMapping]:
        """
        Map NL phrase to specific code fragment.

        Strategy:
        1. Look at sibling nodes to understand context
        2. Find relevant AST node based on semantic meaning
        3. For "load" → find read_csv call
        4. For "dataset" → find filename string
        5. For "process" → find data processing call
        """
        phrase = intent_node.content.lower()

        # Find the line where sibling nodes are mapped
        sibling_lines = [m.line for m in sibling_mappings if m]
        if not sibling_lines:
            return None

        # Analyze phrase meaning
        if 'load' in phrase or 'read' in phrase:
            # Find read_csv or similar loading call
            for call_node, line, col_start, col_end in self.call_nodes:
                if isinstance(call_node.func, ast.Attribute):
                    if call_node.func.attr in ('read_csv', 'read_excel', 'load'):
                        code_text = self._extract_text(line, col_start, col_end)
                        return ASTMapping(
                            node_id=intent_node.id,
                            ast_node=call_node,
                            line=line,
                            col_start=col_start,
                            col_end=col_end,
                            code_text=code_text,
                            confidence=0.75,
                            mapping_type='semantic'
                        )

        elif 'dataset' in phrase or 'data' in phrase or 'file' in phrase:
            # Find filename string in read_csv call
            for call_node, line, col_start, col_end in self.call_nodes:
                if isinstance(call_node.func, ast.Attribute):
                    if call_node.func.attr in ('read_csv', 'read_excel'):
                        # Get first argument (filename)
                        if call_node.args:
                            arg = call_node.args[0]
                            if isinstance(arg, ast.Constant):
                                arg_col_start = getattr(arg, 'col_offset', col_start)
                                arg_col_end = getattr(arg, 'end_col_offset', arg_col_start)
                                code_text = self._extract_text(line, arg_col_start, arg_col_end)
                                return ASTMapping(
                                    node_id=intent_node.id,
                                    ast_node=arg,
                                    line=line,
                                    col_start=arg_col_start,
                                    col_end=arg_col_end,
                                    code_text=code_text,
                                    confidence=0.7,
                                    mapping_type='semantic'
                                )

        elif 'process' in phrase or 'clean' in phrase or 'transform' in phrase:
            # Find data processing call (dropna, fillna, transform, etc.)
            for call_node, line, col_start, col_end in self.call_nodes:
                if isinstance(call_node.func, ast.Attribute):
                    if call_node.func.attr in ('dropna', 'fillna', 'transform', 'apply'):
                        code_text = self._extract_text(line, col_start, col_end)
                        return ASTMapping(
                            node_id=intent_node.id,
                            ast_node=call_node,
                            line=line,
                            col_start=col_start,
                            col_end=col_end,
                            code_text=code_text,
                            confidence=0.75,
                            mapping_type='semantic'
                        )

        # Fallback: map to same line as siblings (coarse)
        if sibling_mappings:
            primary = sibling_mappings[0]
            return ASTMapping(
                node_id=intent_node.id,
                ast_node=primary.ast_node,
                line=primary.line,
                col_start=primary.col_start,
                col_end=primary.col_end,
                code_text=primary.code_text,
                confidence=0.5,
                mapping_type='inferred'
            )

        return None

    def map_function_def(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map function definition to FunctionDef AST node"""
        func_name = intent_node.content

        candidates = []
        for func_def, line in self.function_def_nodes:
            if func_def.name == func_name:
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance * 10

                candidates.append((score, func_def, line))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, func_def, line = candidates[0]

            # Map to function name (not entire def)
            col_start = getattr(func_def, 'col_offset', 0) + 4  # After 'def '
            col_end = col_start + len(func_name)
            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=intent_node.id,
                ast_node=func_def,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.95,
                mapping_type='exact'
            )

        return None

    def map_parameter(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map parameter to arg node in function signature"""
        param_name = intent_node.content

        # Look for function definitions near expected line
        candidates = []
        for func_def, line in self.function_def_nodes:
            # Check if this parameter is in the function's args
            for arg in func_def.args.args:
                if arg.arg == param_name:
                    score = 100

                    # Prefer matches closer to expected line
                    if expected_line:
                        distance = abs(line - expected_line)
                        score -= distance * 10

                    candidates.append((score, arg, line, func_def))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, arg, line, func_def = candidates[0]

            # Approximate column position (after function name and '(')
            col_start = getattr(arg, 'col_offset', 0)
            col_end = getattr(arg, 'end_col_offset', col_start + len(param_name))
            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=intent_node.id,
                ast_node=arg,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.9,
                mapping_type='exact'
            )

        return None

    def map_operator(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map operator to BinOp AST node"""
        operator = intent_node.content

        # Map operator symbols to AST types
        op_mapping = {
            '+': ast.Add,
            '-': ast.Sub,
            '*': ast.Mult,
            '/': ast.Div,
            '//': ast.FloorDiv,
            '%': ast.Mod,
            '**': ast.Pow,
        }

        op_class = op_mapping.get(operator)
        if not op_class:
            return None

        candidates = []
        for binop, line, col_start, col_end in self.binop_nodes:
            if isinstance(binop.op, op_class):
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance * 20

                candidates.append((score, binop, line, col_start, col_end))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, binop, line, col_start, col_end = candidates[0]

            # Find operator position in the line
            line_text = self.code_lines[line - 1] if line <= len(self.code_lines) else ""
            op_pos = line_text.find(operator, col_start)
            if op_pos >= 0:
                op_col_start = op_pos
                op_col_end = op_pos + len(operator)
                code_text = self._extract_text(line, op_col_start, op_col_end)
            else:
                op_col_start = col_start
                op_col_end = col_end
                code_text = operator

            return ASTMapping(
                node_id=intent_node.id,
                ast_node=binop,
                line=line,
                col_start=op_col_start,
                col_end=op_col_end,
                code_text=code_text,
                confidence=0.85,
                mapping_type='exact'
            )

        return None

    def map_literal(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map literal to Constant AST node"""
        literal_value = intent_node.content

        # Try to parse as Python literal
        try:
            # Convert to actual value for comparison
            import ast as ast_module
            parsed_value = ast_module.literal_eval(literal_value)
        except:
            parsed_value = literal_value

        candidates = []
        for constant, line, col_start, col_end in self.constant_nodes:
            # Check if values match
            if constant.value == parsed_value or str(constant.value) == literal_value:
                score = 100

                # Strongly prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance * 20

                candidates.append((score, constant, line, col_start, col_end))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, constant, line, col_start, col_end = candidates[0]

            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=intent_node.id,
                ast_node=constant,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.9,
                mapping_type='exact'
            )

        return None

    def map_import(
        self,
        intent_node,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map import to Import/ImportFrom AST node"""
        module_name = intent_node.content

        candidates = []
        for import_node, line in self.import_nodes:
            matched = False

            if isinstance(import_node, ast.Import):
                # import module
                for alias in import_node.names:
                    if alias.name == module_name or alias.name.startswith(module_name + '.'):
                        matched = True
                        break

            elif isinstance(import_node, ast.ImportFrom):
                # from module import ...
                if import_node.module == module_name or (import_node.module and import_node.module.startswith(module_name + '.')):
                    matched = True

            if matched:
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance * 10

                candidates.append((score, import_node, line))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, import_node, line = candidates[0]

            # Find module name position
            line_text = self.code_lines[line - 1] if line <= len(self.code_lines) else ""
            col_start = line_text.find(module_name)
            if col_start >= 0:
                col_end = col_start + len(module_name)
                code_text = self._extract_text(line, col_start, col_end)
            else:
                col_start = 0
                col_end = len(line_text)
                code_text = line_text

            return ASTMapping(
                node_id=intent_node.id,
                ast_node=import_node,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.9,
                mapping_type='exact'
            )

        return None

    def _extract_text(self, line: int, col_start: int, col_end: int) -> str:
        """Extract text from code at specific position"""
        if 1 <= line <= len(self.code_lines):
            line_text = self.code_lines[line - 1]
            if col_end <= len(line_text):
                return line_text[col_start:col_end]
        return ""

    def map_all_nodes(self, intent_nodes: List) -> List[ASTMapping]:
        """Map all intent nodes to AST nodes"""
        mappings = []
        nodes_by_line = {}

        # Group by semiformal line
        for node in intent_nodes:
            sf_line = node.span[0] if hasattr(node, 'span') else 0
            if sf_line not in nodes_by_line:
                nodes_by_line[sf_line] = []
            nodes_by_line[sf_line].append(node)

        # Map each line
        for sf_line, nodes in nodes_by_line.items():
            line_mappings = []

            # First pass: map concrete Python constructs
            for node in nodes:
                mapping = None

                if node.type == 'identifier':
                    mapping = self.map_identifier(node, sf_line)

                elif node.type == 'function_call':
                    mapping = self.map_function_call(node, sf_line)

                elif node.type == 'function_def':
                    mapping = self.map_function_def(node, sf_line)

                elif node.type == 'parameter':
                    mapping = self.map_parameter(node, sf_line)

                elif node.type == 'operator':
                    mapping = self.map_operator(node, sf_line)

                elif node.type == 'literal':
                    mapping = self.map_literal(node, sf_line)

                elif node.type == 'import':
                    mapping = self.map_import(node, sf_line)

                if mapping:
                    mappings.append(mapping)
                    line_mappings.append(mapping)

            # Second pass: map NL phrases using sibling context
            for node in nodes:
                if node.type in ('nl_phrase', 'hole'):
                    mapping = self.map_nl_phrase(node, line_mappings)
                    if mapping:
                        mappings.append(mapping)

                elif node.type == 'expr_stmt':
                    # Map to same as siblings
                    if line_mappings:
                        primary = line_mappings[0]
                        mappings.append(ASTMapping(
                            node_id=node.id,
                            ast_node=primary.ast_node,
                            line=primary.line,
                            col_start=primary.col_start,
                            col_end=primary.col_end,
                            code_text=primary.code_text,
                            confidence=0.6,
                            mapping_type='inferred'
                        ))

        return mappings
