import re
import ast
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple, Set, Optional
import difflib


@dataclass
class _ASTMatch:
    """Internal helper for content-based matching between IR nodes and AST"""
    ast_node: ast.AST
    line: int
    context: str
    score: float = 0.0


class CodePostprocessor:
    """Postprocess LLM-generated code and build mapping"""
    
    def __init__(self):
        self.anchor_pattern = re.compile(r'#\s*([^#\n]+?)(?=\s*#|\s*$)')
    
    def process_generated_output(
        self,
        llm_output: str,
        mode: str,  # 'full' or 'diff'
        existing_code: str = "",
        parsed_nodes: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main postprocessing pipeline
        
        Returns:
            {
                'code': str,  # Final Python code
                'ast': ast.Module,  # Parsed AST
                'sdg': Dict,  # System Dependence Graph
                'mapping': Dict,  # Semiformal node → code mapping
                'anchors': Dict,  # Anchor → AST node mapping
                'coverage': float,  # Coverage percentage
            }
        """
        
        # Step 1: Extract code from LLM output
        if mode == 'diff':
            final_code = self.apply_diff_patch(existing_code, llm_output)
        else:
            final_code = self.extract_code_block(llm_output)
        
        # Step 1.5: Strip non-anchor comments so only anchor comments remain (using `#>` syntax)
        final_code = self._strip_non_anchor_comments(final_code)
        
        # Step 2: Parse Python AST
        try:
            code_ast = ast.parse(final_code)
        except SyntaxError as e:
            return {
                'error': f'Syntax error in generated code: {e}',
                'code': final_code,
            }
        
        # Step 3: Build SDG (System Dependence Graph)
        sdg = self.build_sdg(code_ast, final_code)
        
        # Step 4: Extract anchor map (anchor → AST nodes)
        anchor_map = self.extract_anchor_map(code_ast, final_code)
        # Step 5: Build mapping (semiformal nodes → code)
        if parsed_nodes:
            mapping = self.build_node_mapping(parsed_nodes, anchor_map, code_ast, sdg)
            coverage = self.compute_coverage(mapping, code_ast)
        else:
            mapping = {}
            coverage = 0.0
        
        return {
            'code': final_code,
            'ast': code_ast,
            'sdg': sdg,
            'mapping': mapping,
            'anchors': anchor_map,
            'coverage': coverage,
        }
    
    def _strip_non_anchor_comments(self, code_text: str) -> str:
        """
        Remove all comments except anchor comments using the `#>` syntax.
        
        - If a line contains `#>`, we keep the code and the `#>` anchor comment,
          but drop any other comment fragments before it.
        - If a line has `#` but no `#>`, we strip everything from the first `#`
          onwards (leaving just the code).
        """
        lines = code_text.split('\n')
        new_lines: List[str] = []
        
        for line in lines:
            anchor_idx = line.find('#>')
            if anchor_idx != -1:
                # Preserve code before anchor, but strip any earlier comment
                first_hash_idx = line.find('#')
                if first_hash_idx != -1 and first_hash_idx < anchor_idx:
                    base = line[:first_hash_idx].rstrip()
                else:
                    base = line[:anchor_idx]
                new_line = base + line[anchor_idx:]
            else:
                # No anchor comment - strip normal comments
                hash_idx = line.find('#')
                if hash_idx != -1:
                    new_line = line[:hash_idx].rstrip()
                else:
                    new_line = line
            new_lines.append(new_line.rstrip())
        
        return '\n'.join(new_lines)
    
    # ============================================================
    # Step 1: Code Extraction
    # ============================================================
    
    def extract_code_block(self, llm_output: str) -> str:
        """Extract Python code from markdown code blocks"""
        
        # Try to find ```python ... ``` blocks
        python_block_pattern = r'```python\n(.*?)```'
        matches = re.findall(python_block_pattern, llm_output, re.DOTALL)
        
        if matches:
            # Return the first (or longest) code block
            return max(matches, key=len).strip()
        
        # Try generic ``` blocks
        generic_block_pattern = r'```\n(.*?)```'
        matches = re.findall(generic_block_pattern, llm_output, re.DOTALL)
        
        if matches:
            # Filter out non-Python blocks (e.g., diff blocks)
            for match in matches:
                if not match.strip().startswith('---'):  # Not a diff
                    return match.strip()
        
        # If no code blocks, return the whole output (assume it's raw code)
        return llm_output.strip()
    
    def apply_diff_patch(self, existing_code: str, diff_output: str) -> str:
        """Apply git diff patch to existing code"""
        
        # Extract diff from markdown if present
        diff_text = self.extract_diff_block(diff_output)
        
        # Parse unified diff
        existing_lines = existing_code.splitlines(keepends=True)
        
        # Apply the patch
        patched_lines = self._apply_unified_diff(existing_lines, diff_text)
        
        return ''.join(patched_lines)
    
    def extract_diff_block(self, llm_output: str) -> str:
        """Extract diff from markdown code block"""
        
        # Try ```diff ... ``` (with optional whitespace/newlines)
        diff_block_pattern = r'```\s*diff\s*\n(.*?)```'
        matches = re.findall(diff_block_pattern, llm_output, re.DOTALL)
        
        if matches:
            return matches[0].strip()
        
        # Try generic ``` block that looks like diff (starts with --- or @@)
        generic_pattern = r'```\s*\n(---.*?)```'
        matches = re.findall(generic_pattern, llm_output, re.DOTALL)
        
        if matches:
            content = matches[0].strip()
            # Verify it looks like a diff
            if content.startswith('---') or '@@' in content:
                return content
        
        # Try to find diff markers directly (--- and +++)
        if '---' in llm_output and '+++' in llm_output:
            # Extract from first --- to end or next markdown block
            lines = llm_output.split('\n')
            diff_start = None
            for i, line in enumerate(lines):
                if line.startswith('---'):
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
        
        # Assume the whole output is the diff
        return llm_output.strip()
    
    def _apply_unified_diff(self, original_lines: List[str], diff_text: str) -> List[str]:
        """Apply unified diff format to original lines using context-aware matching"""
        
        # Parse diff into hunks with full context
        hunks = self._parse_unified_diff(diff_text)
        
        # Apply hunks in reverse order (to maintain line numbers)
        result_lines = original_lines.copy()
        
        for hunk in reversed(hunks):
            # Find the location using context matching
            location = self._find_hunk_location(result_lines, hunk)
            
            if location is None:
                # Fallback: use the line number from hunk header
                location = hunk['old_start'] - 1
                if location < 0:
                    location = 0
                if location >= len(result_lines):
                    location = len(result_lines)
            
            # Process hunk lines in order
            # Context lines are kept as-is, removed lines are deleted, added lines are inserted
            current_pos = location
            
            for hunk_line in hunk['hunk_lines']:
                if hunk_line['type'] == 'context':
                    # Context line should match existing line - verify and advance
                    expected = hunk_line['content'].rstrip('\n\r')
                    
                    # Skip empty lines in original if expected is not empty
                    if expected.strip():  # Expected line is not empty
                        while current_pos < len(result_lines) and result_lines[current_pos].strip() == '':
                            current_pos += 1
                    
                    if current_pos < len(result_lines):
                        # Verify context matches
                        actual = result_lines[current_pos].rstrip('\n\r')
                        if expected == actual or (not expected.strip() and not actual.strip()):
                            # Match - advance
                            current_pos += 1
                        else:
                            # Context mismatch - try to find matching line nearby
                            found = False
                            for offset in range(1, min(5, len(result_lines) - current_pos)):
                                if current_pos + offset < len(result_lines):
                                    candidate = result_lines[current_pos + offset].rstrip('\n\r')
                                    if expected == candidate or (not expected.strip() and not candidate.strip()):
                                        # Found match - skip to it
                                        current_pos += offset + 1
                                        found = True
                                        break
                            if not found:
                                # No match found - still advance to avoid infinite loop
                                # This might cause misalignment, but it's better than hanging
                                current_pos += 1
                    else:
                        # Missing context line - insert it (shouldn't happen in valid diff)
                        line_content = hunk_line['content']
                        # Preserve newline format from original
                        if current_pos > 0 and current_pos <= len(result_lines):
                            # Use newline format from surrounding lines
                            if result_lines[current_pos - 1].endswith('\n'):
                                line_content += '\n'
                        elif len(result_lines) > 0 and result_lines[-1].endswith('\n'):
                            line_content += '\n'
                        result_lines.insert(current_pos, line_content)
                        current_pos += 1
                
                elif hunk_line['type'] == 'removed':
                    # Remove this line from original
                    expected = hunk_line['content'].rstrip('\n\r')
                    
                    # Skip empty lines if expected is not empty
                    if expected.strip():
                        while current_pos < len(result_lines) and result_lines[current_pos].strip() == '':
                            current_pos += 1
                    
                    if current_pos < len(result_lines):
                        # Verify it matches (for safety)
                        actual = result_lines[current_pos].rstrip('\n\r')
                        if expected == actual or (not expected.strip() and not actual.strip()):
                            # Match - remove it
                            result_lines.pop(current_pos)
                        else:
                            # Doesn't match exactly - try to find it nearby
                            found = False
                            for offset in range(0, min(5, len(result_lines) - current_pos)):
                                if current_pos + offset < len(result_lines):
                                    candidate = result_lines[current_pos + offset].rstrip('\n\r')
                                    if expected == candidate:
                                        # Found match - remove it
                                        result_lines.pop(current_pos + offset)
                                        found = True
                                        break
                            if not found:
                                # Not found - remove current line anyway (might be formatting diff)
                                result_lines.pop(current_pos)
                    # Don't advance current_pos - we removed a line (or tried to)
                
                elif hunk_line['type'] == 'added':
                    # Insert new line
                    line_content = hunk_line['content']
                    # Preserve newline format from original file
                    # Check surrounding lines to determine newline format
                    needs_newline = False
                    if current_pos < len(result_lines):
                        needs_newline = result_lines[current_pos].endswith('\n')
                    elif current_pos > 0:
                        needs_newline = result_lines[current_pos - 1].endswith('\n')
                    elif len(result_lines) > 0:
                        needs_newline = result_lines[-1].endswith('\n')
                    
                    if needs_newline and not line_content.endswith('\n'):
                        line_content += '\n'
                    result_lines.insert(current_pos, line_content)
                    current_pos += 1
        
        return result_lines
    
    def _parse_unified_diff(self, diff_text: str) -> List[Dict[str, Any]]:
        """Parse unified diff format into structured hunks with full context"""
        
        hunks = []
        current_hunk = None
        
        lines = diff_text.split('\n')
        
        for line in lines:
            # Skip diff header lines (---, +++)
            if line.startswith('---') or line.startswith('+++'):
                continue
            
            # Match hunk header: @@ -start,count +start,count @@ or @@ -start +start,count @@
            # Handle both formats: with and without comma (single line changes)
            hunk_match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
            
            if hunk_match:
                # Save previous hunk
                if current_hunk:
                    hunks.append(current_hunk)
                
                # Parse hunk header
                old_start = int(hunk_match.group(1))
                old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
                new_start = int(hunk_match.group(3))
                new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 1
                
                # Start new hunk
                current_hunk = {
                    'old_start': old_start,
                    'old_count': old_count,
                    'new_start': new_start,
                    'new_count': new_count,
                    'hunk_lines': [],  # List of {'type': 'context'|'removed'|'added', 'content': str}
                }
            
            elif current_hunk:
                # Parse hunk content lines
                if line.startswith(' '):
                    # Context line (unchanged)
                    current_hunk['hunk_lines'].append({
                        'type': 'context',
                        'content': line[1:]  # Remove leading space
                    })
                elif line.startswith('-'):
                    # Removed line
                    current_hunk['hunk_lines'].append({
                        'type': 'removed',
                        'content': line[1:]  # Remove leading -
                    })
                elif line.startswith('+'):
                    # Added line
                    current_hunk['hunk_lines'].append({
                        'type': 'added',
                        'content': line[1:]  # Remove leading +
                    })
                # Empty lines or other lines are ignored
        
        # Save last hunk
        if current_hunk:
            hunks.append(current_hunk)
        
        return hunks
    
    def _find_hunk_location(self, original_lines: List[str], hunk: Dict[str, Any]) -> Optional[int]:
        """
        Find the location in original_lines where this hunk should be applied.
        Uses context matching like real patch tools.
        
        Returns:
            Line index (0-based) where hunk should be applied, or None if not found
        """
        # Build a sequence of lines that should appear in the original file
        # This includes context lines and removed lines (in order)
        expected_sequence = []
        for hunk_line in hunk['hunk_lines']:
            if hunk_line['type'] in ('context', 'removed'):
                # Both context and removed lines should be in the original
                content = hunk_line['content'].rstrip('\n\r')
                expected_sequence.append(content)
        
        if not expected_sequence:
            # No context to match, use line number from hunk
            return hunk['old_start'] - 1
        
        # Try to find matching sequence in original file
        # Start searching from the expected location (hunk['old_start'] - 1)
        expected_start = hunk['old_start'] - 1
        
        # Search in a window around the expected location (wider window for robustness)
        search_start = max(0, expected_start - 20)
        search_end = min(len(original_lines), expected_start + 20)
        
        for i in range(search_start, search_end - len(expected_sequence) + 1):
            # Check if sequence matches at this position
            # Use a more flexible matching that skips extra empty lines
            match = True
            orig_idx = i
            for expected_line in expected_sequence:
                # Skip empty lines in original if expected is not empty
                while orig_idx < len(original_lines) and not expected_line.strip() and original_lines[orig_idx].strip() == '':
                    orig_idx += 1
                
                if orig_idx >= len(original_lines):
                    match = False
                    break
                
                # Compare lines (strip newlines and carriage returns for comparison)
                orig_line = original_lines[orig_idx].rstrip('\n\r')
                expected_stripped = expected_line.rstrip('\n\r')
                
                # Allow empty lines to match any empty line
                if not expected_stripped and not orig_line:
                    orig_idx += 1
                    continue
                
                if orig_line != expected_stripped:
                    match = False
                    break
                
                orig_idx += 1
            
            if match:
                return i
        
        # If no match found, return expected location (fallback)
        # This allows the patch to be applied even if context doesn't match exactly
        return expected_start
    
    # ============================================================
    # Step 3: Build SDG
    # ============================================================
    
    def build_sdg(self, code_ast: ast.Module, code_text: str) -> Dict[str, Any]:
        """
        Build System Dependence Graph
        
        Returns:
            {
                'nodes': List[Dict],  # All AST nodes
                'data_deps': Dict[node_id, List[node_id]],
                'control_deps': Dict[node_id, List[node_id]],
                'call_deps': Dict[node_id, node_id],  # call → function def
            }
        """
        
        sdg = {
            'nodes': [],
            'data_deps': {},
            'control_deps': {},
            'call_deps': {},
        }
        
        # Collect all nodes with IDs
        node_id = 0
        node_map = {}
        
        for node in ast.walk(code_ast):
            node._id = node_id
            node_map[node_id] = node
            sdg['nodes'].append({
                'id': node_id,
                'type': type(node).__name__,
                'lineno': getattr(node, 'lineno', -1),
            })
            node_id += 1
        
        # Build data dependencies (def-use chains)
        sdg['data_deps'] = self._build_data_dependencies(code_ast, node_map)
        
        # Build control dependencies
        sdg['control_deps'] = self._build_control_dependencies(code_ast, node_map)
        
        # Build call dependencies
        sdg['call_deps'] = self._build_call_dependencies(code_ast, node_map)
        
        return sdg
    
    def _build_data_dependencies(
        self, 
        code_ast: ast.Module, 
        node_map: Dict[int, ast.AST]
    ) -> Dict[int, List[int]]:
        """Build data dependency edges (def → use)"""
        
        data_deps = {}
        
        # Track variable definitions
        defs = {}  # var_name → node_id
        
        for node_id, node in node_map.items():
            # Check for variable definitions
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defs[target.id] = node_id
            
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    defs[node.target.id] = node_id
            
            # Check for variable uses
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                var_name = node.id
                if var_name in defs:
                    # Add edge: def → use
                    def_id = defs[var_name]
                    if def_id not in data_deps:
                        data_deps[def_id] = []
                    data_deps[def_id].append(node_id)
        
        return data_deps
    
    def _build_control_dependencies(
        self,
        code_ast: ast.Module,
        node_map: Dict[int, ast.AST]
    ) -> Dict[int, List[int]]:
        """Build control dependency edges"""
        
        control_deps = {}
        
        for node_id, node in node_map.items():
            # If/For/While control flow
            if isinstance(node, (ast.If, ast.For, ast.While)):
                # All nodes in body are control-dependent on this node
                body_nodes = []
                for child in ast.walk(node):
                    if hasattr(child, '_id'):
                        body_nodes.append(child._id)
                
                control_deps[node_id] = body_nodes
        
        return control_deps
    
    def _build_call_dependencies(
        self,
        code_ast: ast.Module,
        node_map: Dict[int, ast.AST]
    ) -> Dict[int, int]:
        """Build call → function definition edges"""
        
        call_deps = {}
        
        # Build function definition map
        func_defs = {}  # func_name → node_id
        for node_id, node in node_map.items():
            if isinstance(node, ast.FunctionDef):
                func_defs[node.name] = node_id
        
        # Find calls and link to definitions
        for node_id, node in node_map.items():
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in func_defs:
                        call_deps[node_id] = func_defs[func_name]
        
        return call_deps
    
    # ============================================================
    # Step 4: Extract Anchor Map
    # ============================================================
    
    def extract_anchor_map(
        self,
        code_ast: ast.Module,
        code_text: str
    ) -> Dict[str, List[Tuple[ast.AST, int]]]:
        """
        Extract anchors from code comments
        
        Returns:
            Dict[anchor_str, List[Tuple[ast_node, line_number]]]
        """
        
        anchor_map = {}
        
        # Get code lines
        code_lines = code_text.split('\n')
        
        # For each line with anchors
        for line_num, line in enumerate(code_lines, start=1):
            # Extract anchors from comment
            anchors = self._extract_anchors_from_line(line)
            
            if not anchors:
                continue
            
            # Find AST node(s) on this line
            nodes_on_line = self._find_nodes_on_line(code_ast, line_num)
            
            # Map each anchor to these nodes
            for anchor in anchors:
                if anchor not in anchor_map:
                    anchor_map[anchor] = []
                
                for node in nodes_on_line:
                    anchor_map[anchor].append((node, line_num))
        
        return anchor_map
    
    def _extract_anchors_from_line(self, line: str) -> List[str]:
        """Extract anchor strings from a line of code"""
        
        # Find anchor comment part using `#>` marker
        comment_match = re.search(r'#\>(.*)$', line)
        if not comment_match:
            return []
        
        comment_text = comment_match.group(1)
        
        # Split by semicolon or multiple # symbols
        # Anchors are separated by ; or by #
        anchors = []
        
        # Method 1: Split by semicolon
        parts = comment_text.split(';')
        for part in parts:
            part = part.strip()
            # Remove leading # if present
            if part.startswith('#'):
                part = part[1:].strip()
            if part:
                anchors.append(part)
        
        # If no semicolons, try splitting by #
        if len(anchors) <= 1:
            anchors = []
            parts = comment_text.split('#')
            for part in parts:
                part = part.strip()
                if part:
                    anchors.append(part)
        
        return anchors
    
    def _find_nodes_on_line(
        self,
        code_ast: ast.Module,
        line_num: int
    ) -> List[ast.AST]:
        """Find all AST nodes on a specific line"""
        
        nodes = []
        
        for node in ast.walk(code_ast):
            if hasattr(node, 'lineno') and node.lineno == line_num:
                nodes.append(node)
        
        return nodes
    
    # ============================================================
    # Step 5: Build Mapping
    # ============================================================
    
    def build_node_mapping(
        self,
        parsed_nodes: List[Dict[str, Any]],
        anchor_map: Dict[str, List[Tuple[ast.AST, int]]],
        code_ast: ast.Module,
        sdg: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build mapping from semiformal nodes to code
        
        Returns:
            Dict[node_id, mapping_info]
        """
        
        mapping: Dict[str, Dict[str, Any]] = {}
        
        # Pre-build identifier index for content-based fallback mapping
        identifier_index = self._build_identifier_index(code_ast) if code_ast is not None else {}
        used_ast_ids: Set[int] = set()
        
        for sf_node in parsed_nodes:
            node_id = sf_node.get('id')
            if not node_id:
                # Fallback id if missing
                line = sf_node.get('line', 0)
                col = sf_node.get('col', 0)
                node_id = f"node_{line}_{col}"
            
            # Determine anchor for this node
            anchor = self._determine_anchor_for_node(sf_node)
            
            primary_node: Optional[ast.AST] = None
            primary_line: int = -1
            anchor_nodes: List[Tuple[ast.AST, int]] = []
            
            # 1) Anchor-based mapping (preferred)
            if anchor and anchor in anchor_map:
                anchor_nodes = anchor_map[anchor]
                primary_node, primary_line = self._select_anchor_ast_node(
                    sf_node,
                    anchor_nodes,
                    used_ast_ids
                )
                if primary_node is not None:
                    used_ast_ids.add(id(primary_node))
            else:
                # 2) Content-based fallback mapping using identifier index
                if identifier_index:
                    expected_line = sf_node.get('line')
                    best_match = self._find_best_content_match(
                        sf_node,
                        identifier_index,
                        expected_line,
                        used_ast_ids
                    )
                    if best_match:
                        primary_node = best_match.ast_node
                        primary_line = best_match.line
                        anchor_nodes = [(primary_node, primary_line)]
                        used_ast_ids.add(id(primary_node))
            
            if not primary_node:
                # No mapping found
                mapping[node_id] = {
                    'status': 'unmapped',
                    'node': sf_node,
                    'anchor': anchor,
                }
                continue
            
            # Compute slice from this node
            slice_nodes = self._compute_slice(primary_node, sdg)
            
            mapping[node_id] = {
                'status': 'mapped',
                'node': sf_node,
                'anchor': anchor,
                'code_nodes': [n for n, _ in anchor_nodes],
                'primary_node': primary_node,
                'primary_line': primary_line,
                'slice': slice_nodes,
            }
        
        return mapping
    
    def _determine_anchor_for_node(self, sf_node: Dict[str, Any]) -> Optional[str]:
        """Determine what anchor this semiformal node corresponds to"""
        
        node_type = sf_node.get('type')
        # Support both 'value' (editor/generator dicts) and 'content' keys
        value = sf_node.get('value', sf_node.get('content'))
        
        if node_type == 'identifier':
            return value
        elif node_type == 'nl_phrase':
            # Skip trivial words
            if value.lower() not in ['the', 'a', 'an', 'and', 'or', 'it', 'is']:
                return value
        elif node_type == 'hole':
            return value
        elif node_type == 'function_call':
            return value
        
        return None
    
    # ------------------------------------------------------------
    # Content-based fallback mapping (inspired by UnifiedMapper)
    # ------------------------------------------------------------
    
    def _build_identifier_index(
        self,
        code_ast: ast.Module
    ) -> Dict[str, List[_ASTMatch]]:
        """
        Build index of identifiers, calls, and function defs for content-based matching.
        
        Mirrors the core idea of UnifiedMapper._build_identifier_index.
        """
        identifier_index: Dict[str, List[_ASTMatch]] = {}
        function_bodies: Set[int] = set()
        
        # First, collect all nodes that are inside any function body
        for node in ast.walk(code_ast):
            if isinstance(node, ast.FunctionDef):
                for child in ast.walk(node):
                    function_bodies.add(id(child))
        
        for node in ast.walk(code_ast):
            if isinstance(node, ast.Name):
                name = node.id
                line = getattr(node, 'lineno', 0)
                context = 'assignment_target' if isinstance(node.ctx, ast.Store) else 'reference'
                if id(node) in function_bodies:
                    context = f'function_body_{context}'
                match = _ASTMatch(ast_node=node, line=line, context=context)
                identifier_index.setdefault(name, []).append(match)
            
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                func_name = node.func.id
                line = getattr(node, 'lineno', 0)
                context = 'function_body_call' if id(node) in function_bodies else 'call_site'
                match = _ASTMatch(ast_node=node, line=line, context=context)
                identifier_index.setdefault(func_name, []).append(match)
            
            elif isinstance(node, ast.FunctionDef):
                func_name = node.name
                line = getattr(node, 'lineno', 0)
                match = _ASTMatch(ast_node=node, line=line, context='function_definition')
                identifier_index.setdefault(func_name, []).append(match)
        
        return identifier_index
    
    def _find_best_content_match(
        self,
        sf_node: Dict[str, Any],
        identifier_index: Dict[str, List[_ASTMatch]],
        expected_line: Optional[int] = None,
        used_ast_ids: Optional[Set[int]] = None
    ) -> Optional[_ASTMatch]:
        """Find best AST match for a semiformal node using content-based strategy."""
        name = sf_node.get('value', sf_node.get('content'))
        if not name or name not in identifier_index:
            return None
        
        candidates = identifier_index[name]
        if not candidates:
            return None
        
        scored: List[Tuple[float, _ASTMatch]] = []
        for candidate in candidates:
            if used_ast_ids and id(candidate.ast_node) in used_ast_ids:
                continue
            score = self._score_match(sf_node, candidate, expected_line)
            scored.append((score, candidate))
        
        scored.sort(reverse=True, key=lambda x: x[0])
        if scored and scored[0][0] > 0:
            return scored[0][1]
        return None
    
    def _score_match(
        self,
        sf_node: Dict[str, Any],
        ast_match: _ASTMatch,
        expected_line: Optional[int]
    ) -> float:
        """Score how good a content-based match is."""
        score = 0.0
        node_type = sf_node.get('type')
        metadata = sf_node.get('metadata') or {}
        is_definition = metadata.get('is_definition', False)
        node_role = metadata.get('role', '')
        
        # Match node type to context
        if node_type == 'identifier':
            if is_definition or node_role == 'target':
                if ast_match.context == 'assignment_target':
                    score += 100
                elif 'function_body' in ast_match.context:
                    score += 20
            else:
                if ast_match.context == 'reference':
                    score += 50
                elif ast_match.context == 'assignment_target':
                    score += 30
        
        elif node_type == 'function_call':
            if ast_match.context == 'call_site':
                score += 100
            elif 'function_body' in ast_match.context:
                score += 30
            elif ast_match.context == 'function_definition':
                score += 5
        
        elif node_type == 'function_def':
            if ast_match.context == 'function_definition':
                score += 100
        
        # Prefer main code over function bodies
        if 'function_body' not in ast_match.context:
            score += 50
        
        # Prefer matches closer to expected line (if provided, 1-based)
        if expected_line is not None and ast_match.line > 0:
            line_distance = abs(ast_match.line - expected_line)
            score += max(0, 30 - line_distance)
        
        return score

    def _select_anchor_ast_node(
        self,
        sf_node: Dict[str, Any],
        anchor_nodes: List[Tuple[ast.AST, int]],
        used_ast_ids: Set[int]
    ) -> Tuple[Optional[ast.AST], int]:
        """
        Select the best AST node on a line for a given semiformal node and anchor.
        
        This disambiguates multiple occurrences on the same line, e.g.:
          x, y = train_test_split(...)  # x # y # split data ...
        so that:
          - `x` maps to the Name `x`,
          - `y` maps to the Name `y`,
          - the NL hole maps to the Call `train_test_split(...)`.
        """
        if not anchor_nodes:
            return None, -1
        
        node_type = sf_node.get('type')
        value = sf_node.get('value', sf_node.get('content'))
        expected_line = sf_node.get('line')
        
        best_node: Optional[ast.AST] = None
        best_line: int = -1
        best_score: float = -1.0
        
        for ast_node, line in anchor_nodes:
            if id(ast_node) in used_ast_ids:
                continue
            
            score = 0.0
            
            # Strong type-based preferences
            if node_type == 'identifier':
                if isinstance(ast_node, ast.Name) and isinstance(ast_node.ctx, ast.Store):
                    if value and ast_node.id == value:
                        score += 120
                    elif value and value in ast_node.id:
                        score += 60
                elif isinstance(ast_node, ast.Name):
                    if value and ast_node.id == value:
                        score += 80
            elif node_type == 'function_call':
                if isinstance(ast_node, ast.Call):
                    func_name = ""
                    if isinstance(ast_node.func, ast.Name):
                        func_name = ast_node.func.id
                    elif isinstance(ast_node.func, ast.Attribute):
                        try:
                            func_name = ast.unparse(ast_node.func)
                        except Exception:
                            func_name = ""
                    if value and func_name and value in func_name:
                        score += 120
                    else:
                        score += 60
            elif node_type in ('nl_phrase', 'hole'):
                # Map NL/hole anchors to "bigger" operations: calls or RHS expressions
                if isinstance(ast_node, ast.Call):
                    score += 100
                elif isinstance(ast_node, (ast.Assign, ast.Expr, ast.Return)):
                    score += 60
                else:
                    score += 20
            
            # Line proximity bonus
            if expected_line is not None and line > 0:
                line_distance = abs(line - expected_line)
                score += max(0, 20 - line_distance)
            
            if score > best_score:
                best_score = score
                best_node = ast_node
                best_line = line
        
        if best_node is None:
            return None, -1
        
        return best_node, best_line
    
    def _compute_slice(
        self,
        anchor_node: ast.AST,
        sdg: Dict[str, Any]
    ) -> Set[int]:
        """Compute backward + forward slice from anchor node"""
        
        if not hasattr(anchor_node, '_id'):
            return set()
        
        anchor_id = anchor_node._id
        
        # Backward slice (dependencies)
        backward = self._backward_slice(anchor_id, sdg, max_depth=2)
        
        # Forward slice (uses)
        forward = self._forward_slice(anchor_id, sdg, max_depth=1)
        
        return backward | {anchor_id} | forward
    
    def _backward_slice(
        self,
        node_id: int,
        sdg: Dict[str, Any],
        max_depth: int = 2
    ) -> Set[int]:
        """Compute backward slice with depth limit"""
        
        visited = set()
        worklist = [(node_id, 0)]
        
        while worklist:
            current, depth = worklist.pop()
            
            if current in visited or depth > max_depth:
                continue
            
            visited.add(current)
            
            # Follow data dependencies backward
            # (reverse lookup: find nodes that current depends on)
            for dep_id, targets in sdg['data_deps'].items():
                if current in targets:
                    worklist.append((dep_id, depth + 1))
            
            # Follow control dependencies backward
            for ctrl_id, dependents in sdg['control_deps'].items():
                if current in dependents:
                    worklist.append((ctrl_id, depth + 1))
            
            # Follow call dependencies (into function bodies)
            if current in sdg['call_deps']:
                func_def_id = sdg['call_deps'][current]
                worklist.append((func_def_id, 0))  # Reset depth in function
        
        return visited
    
    def _forward_slice(
        self,
        node_id: int,
        sdg: Dict[str, Any],
        max_depth: int = 1
    ) -> Set[int]:
        """Compute forward slice"""
        
        visited = set()
        worklist = [(node_id, 0)]
        
        while worklist:
            current, depth = worklist.pop()
            
            if current in visited or depth > max_depth:
                continue
            
            visited.add(current)
            
            # Follow data dependencies forward
            if current in sdg['data_deps']:
                for target in sdg['data_deps'][current]:
                    worklist.append((target, depth + 1))
        
        return visited
    
    # ============================================================
    # Coverage Computation
    # ============================================================
    
    def compute_coverage(
        self,
        mapping: Dict[str, Dict[str, Any]],
        code_ast: ast.Module
    ) -> float:
        """Compute what percentage of code is covered by mappings"""
        
        # Collect all covered nodes
        covered_nodes = set()
        for node_id, mapping_info in mapping.items():
            if mapping_info['status'] == 'mapped':
                covered_nodes.update(mapping_info['slice'])
        
        # Count total nodes
        total_nodes = len([n for n in ast.walk(code_ast)])
        
        if total_nodes == 0:
            return 0.0
        
        return len(covered_nodes) / total_nodes