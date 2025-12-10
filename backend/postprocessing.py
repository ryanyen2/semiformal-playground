import re
import ast
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple, Set, Optional
import difflib
import diff_match_patch as dmp_module


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
        self.dmp = dmp_module.diff_match_patch()
    
    def process_generated_output(
        self,
        llm_output: str,
        mode: str,  # 'full' or 'diff'
        existing_code: str = "",
        parsed_nodes: List[Dict[str, Any]] = None,
        existing_semiformal: str = ""  # NEW: Track existing semiformal for stub detection
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
                'changed_lines': List[int],  # Line numbers that were added/changed
            }
        """
        
        # Step 1: Extract code from LLM output (always full code now)
        final_code = self.extract_code_block(llm_output)
        
        # Step 1.5: Compute diff and track changed lines
        changed_lines = []
        if mode == 'diff' and existing_code:
            changed_lines = self.compute_changed_lines(existing_code, final_code)
        
        # Step 1.6: Strip non-anchor comments so only anchor comments remain (using `#>` syntax)
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
            unmapped_code = self.identify_unmapped_code(mapping, code_ast, final_code)
        else:
            mapping = {}
            coverage = 0.0
            unmapped_code = []
        
        # Step 6: Extract inferred code (function bodies with #< annotations)
        inferred_info = self.extract_inferred_semiformal(
            code_ast, final_code, mapping, 
            parsed_nodes if parsed_nodes else None,
            existing_semiformal=existing_semiformal  # Pass existing semiformal for stub detection
        )
        print('inferred_info', inferred_info)
        
        # Step 7: Extract function signatures for syncing stubs
        function_signatures = self.extract_function_signatures(final_code)
        
        return {
            'code': final_code,
            'ast': code_ast,
            'sdg': sdg,
            'mapping': mapping,
            'anchors': anchor_map,
            'coverage': coverage,
            'unmapped_code': unmapped_code,
            'inferred_semiformal': inferred_info.get('code', ''),
            'inferred_insertions': inferred_info.get('insertions', []),
            'inferred_replacements': inferred_info.get('replacements', []),  # NEW: Track replacements
            'function_signatures': function_signatures,
            'changed_lines': changed_lines,  # NEW: Track changed lines for gutter decorations
        }
    
    def compute_changed_lines(self, old_code: str, new_code: str) -> List[int]:
        """
        Compute which lines were added or changed using diff-match-patch.
        
        Returns:
            List of line numbers (1-indexed) that were added or modified
        """
        # Use diff-match-patch for efficient diffing
        diffs = self.dmp.diff_main(old_code, new_code)
        self.dmp.diff_cleanupSemantic(diffs)
        
        changed_lines = set()
        current_line = 1
        
        for op, text in diffs:
            if op == dmp_module.diff_match_patch.DIFF_DELETE:
                # Track deletions by line numbers in old code
                line_count = text.count('\\n')
                current_line += line_count
            elif op == dmp_module.diff_match_patch.DIFF_INSERT:
                # Track insertions by line numbers in new code
                line_count = text.count('\\n')
                for i in range(line_count + 1):
                    if text.strip():  # Only mark non-empty lines
                        changed_lines.add(current_line + i)
                current_line += line_count
            else:  # DIFF_EQUAL
                # Update line counter for equal sections
                line_count = text.count('\\n')
                current_line += line_count
        
        return sorted(list(changed_lines))
    
    def _strip_non_anchor_comments(self, code_text: str) -> str:
        """
        Remove all comments except anchor comments using the `#>` and `#<` syntax.
        
        - If a line contains `#>` or `#<`, we keep the code and the anchor comment,
          but drop any other comment fragments before it.
        - If a line has both `#>` and `#<`, we keep only `#>` (since `#>` means it's
          now explicitly specified, so `#<` is redundant).
        - If a line has `#` but no `#>` or `#<`, we strip everything from the first `#`
          onwards (leaving just the code).
        """
        lines = code_text.split('\n')
        new_lines: List[str] = []
        
        for line in lines:
            anchor_idx = line.find('#>')
            inferred_idx = line.find('#<')
            
            # If both are present, prefer #> and remove #<
            if anchor_idx != -1 and inferred_idx != -1:
                # Keep code and #> anchor, remove #< and everything after it (or before if #< comes first)
                if anchor_idx < inferred_idx:
                    # #> comes first, keep it and remove #< part
                    base = line[:anchor_idx].rstrip()
                    # Find where #< starts and remove it
                    inferred_part_start = line.find('#<', anchor_idx)
                    if inferred_part_start != -1:
                        # Remove from #< onwards
                        new_line = base + line[anchor_idx:inferred_part_start].rstrip()
                    else:
                        new_line = base + line[anchor_idx:]
                else:
                    # #< comes first, keep code and #> part only
                    base = line[:inferred_idx].rstrip()
                    # Find #> after #<
                    anchor_part_start = line.find('#>', inferred_idx)
                    if anchor_part_start != -1:
                        # Keep code and #> part
                        new_line = base + line[anchor_part_start:]
                    else:
                        # No #> after #<, just keep code
                        new_line = base
            elif anchor_idx != -1:
                # Only #> present
                first_hash_idx = line.find('#')
                if first_hash_idx != -1 and first_hash_idx < anchor_idx:
                    base = line[:first_hash_idx].rstrip()
                else:
                    base = line[:anchor_idx]
                new_line = base + line[anchor_idx:]
            elif inferred_idx != -1:
                # Only #< present
                first_hash_idx = line.find('#')
                if first_hash_idx != -1 and first_hash_idx < inferred_idx:
                    base = line[:first_hash_idx].rstrip()
                else:
                    base = line[:inferred_idx]
                new_line = base + line[inferred_idx:]
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
    
    def identify_unmapped_code(
        self,
        mapping: Dict[str, Dict[str, Any]],
        code_ast: ast.Module,
        code_text: str
    ) -> List[Dict[str, Any]]:
        """
        Identify code regions that are not mapped to any semiformal node.
        
        Returns:
            List of unmapped regions, each with:
            {
                'line': int,  # Line number (1-based)
                'col': int,   # Column number (0-based)
                'length': int,  # Length of unmapped region
                'text': str,  # The actual code text
            }
        """
        # Collect all covered node IDs
        # Include both slice nodes and all code_nodes that are directly mapped
        covered_node_ids = set()
        for node_id, mapping_info in mapping.items():
            if mapping_info['status'] == 'mapped':
                # Include nodes from the slice (dependencies)
                covered_node_ids.update(mapping_info['slice'])
                
                # Also include all code_nodes that are directly associated with this mapping
                # These are the AST nodes that were matched via anchors
                code_nodes = mapping_info.get('code_nodes', [])
                for ast_node in code_nodes:
                    if hasattr(ast_node, '_id'):
                        covered_node_ids.add(ast_node._id)
                
                # Include the primary node
                primary_node = mapping_info.get('primary_node')
                if primary_node and hasattr(primary_node, '_id'):
                    covered_node_ids.add(primary_node._id)
        
        # Build a map of node_id -> (line, col, text)
        node_info_map = {}
        code_lines = code_text.split('\n')
        
        for node in ast.walk(code_ast):
            if hasattr(node, '_id'):
                node_id = node._id
                line = getattr(node, 'lineno', -1)
                col = getattr(node, 'col_offset', -1)
                
                # Get text representation of this node
                try:
                    node_text = ast.unparse(node)
                    # For multi-line nodes, just get the first line
                    if '\n' in node_text:
                        node_text = node_text.split('\n')[0]
                except Exception:
                    # Fallback: try to extract from code
                    if line > 0 and line <= len(code_lines):
                        line_text = code_lines[line - 1]
                        if col >= 0 and col < len(line_text):
                            # Try to extract a token starting at col
                            remaining = line_text[col:]
                            match = re.match(r'^(\S+)', remaining)
                            if match:
                                node_text = match.group(1)
                            else:
                                node_text = ''
                        else:
                            node_text = ''
                    else:
                        node_text = ''
                
                node_info_map[node_id] = {
                    'line': line,
                    'col': col,
                    'text': node_text,
                    'node': node
                }
        
        # Find unmapped nodes
        unmapped_regions = []
        for node_id, info in node_info_map.items():
            if node_id not in covered_node_ids:
                line = info['line']
                col = info['col']
                text = info['text']
                
                # Only include nodes that have valid line/col info and meaningful text
                if line > 0 and col >= 0 and text and text.strip():
                    # Skip very small nodes like operators, parentheses, etc. that are less meaningful
                    # Focus on identifiers, calls, expressions, statements
                    node = info['node']
                    if isinstance(node, (ast.Name, ast.Call, ast.Attribute, ast.FunctionDef, 
                                        ast.Assign, ast.Expr, ast.Return, ast.If, ast.For, 
                                        ast.While, ast.Import, ast.ImportFrom)):
                        unmapped_regions.append({
                            'line': line,
                            'col': col,
                            'length': len(text),
                            'text': text
                        })
        
        # Sort by line, then by column
        unmapped_regions.sort(key=lambda x: (x['line'], x['col']))
        
        # Merge overlapping or adjacent regions on the same line
        merged_regions = []
        for region in unmapped_regions:
            if not merged_regions:
                merged_regions.append(region)
            else:
                last = merged_regions[-1]
                # If same line and regions overlap or are adjacent (within 2 chars)
                if (last['line'] == region['line'] and 
                    region['col'] <= last['col'] + last['length'] + 2):
                    # Merge: extend the last region
                    last_end = last['col'] + last['length']
                    region_end = region['col'] + region['length']
                    last['length'] = max(last_end, region_end) - last['col']
                    # Update text (use the longer one or combine)
                    if len(region['text']) > len(last['text']):
                        last['text'] = region['text']
                else:
                    merged_regions.append(region)
        
        return merged_regions
    
    def extract_inferred_semiformal(
        self,
        code_ast: ast.Module,
        code_text: str,
        mapping: Dict[str, Dict[str, Any]],
        parsed_nodes: Optional[List[Dict[str, Any]]] = None,
        existing_semiformal: str = ""
    ) -> Dict[str, Any]:
        """
        Extract inferred code (function bodies with #< annotations) and convert to semiformal format.
        
        Focuses on function definitions that were created for incomplete function calls.
        Converts them to semiformal format: `var = NL phrase` form.
        
        Returns:
            Dict with 'code' (semiformal code) and 'insertions' (list of insertion info with line numbers)
        """
        code_lines = code_text.split('\n')
        inferred_insertions = []  # List of {'code': str, 'insert_line': int}
        inferred_replacements = []  # List of {'code': str, 'replace_start_line': int, 'replace_end_line': int}
        
        # Section 0: Parse existing semiformal to find existing stub functions
        existing_stub_functions = {}  # func_name -> (start_line, end_line)
        if existing_semiformal:
            try:
                existing_tree = ast.parse(existing_semiformal)
                for node in ast.walk(existing_tree):
                    if isinstance(node, ast.FunctionDef):
                        start_line = node.lineno - 1  # 0-indexed
                        end_line = node.end_lineno - 1 if hasattr(node, 'end_lineno') else start_line
                        existing_stub_functions[node.name] = (start_line, end_line)
            except SyntaxError:
                pass
        
        # Find all function definitions that are unmapped (created for incomplete calls)
        covered_node_ids = set()
        for node_id, mapping_info in mapping.items():
            if mapping_info['status'] == 'mapped':
                covered_node_ids.update(mapping_info.get('slice', []))
                primary_node = mapping_info.get('primary_node')
                if primary_node and hasattr(primary_node, '_id'):
                    covered_node_ids.add(primary_node._id)
        
        # Build map of function name -> call site line numbers from parsed nodes
        # This helps us find where in the semiformal spec the function is called
        func_call_lines = {}  # func_name -> list of (line_num, node_info)
        if parsed_nodes:
            for sf_node in parsed_nodes:
                if sf_node.get('type') == 'function_call':
                    func_name = sf_node.get('value', sf_node.get('content'))
                    line = sf_node.get('line', 0)
                    if func_name and line > 0:
                        if func_name not in func_call_lines:
                            func_call_lines[func_name] = []
                        func_call_lines[func_name].append((line, sf_node))
        
        # Also find call sites in the generated Python code AST
        python_call_sites = {}  # func_name -> list of line numbers in Python code
        for node in ast.walk(code_ast):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    call_line = getattr(node, 'lineno', 0)
                    if call_line > 0:
                        if func_name not in python_call_sites:
                            python_call_sites[func_name] = []
                        python_call_sites[func_name].append(call_line)
        
        # Track which lines are already part of extracted function definitions
        function_body_lines = set()
        
        # Find unmapped function definitions and map them to call sites
        for node in ast.walk(code_ast):
            if isinstance(node, ast.FunctionDef):
                if hasattr(node, '_id') and node._id not in covered_node_ids:
                    # This function was created by LLM for an incomplete call
                    func_name = node.name
                    func_start_line = getattr(node, 'lineno', 0)
                    
                    if func_start_line > 0:
                        # Mark all lines in this function body
                        func_end_line = func_start_line
                        for child in ast.walk(node):
                            if hasattr(child, 'lineno') and child.lineno > func_start_line:
                                func_end_line = max(func_end_line, child.lineno)
                        
                        # Mark all lines in function body
                        for line_num in range(func_start_line, min(func_end_line + 1, len(code_lines) + 1)):
                            function_body_lines.add(line_num)
                    
                    func_semiformal = self._function_def_to_semiformal(node, code_lines)
                    if func_semiformal:
                        # Ensure function body lines have proper indentation
                        func_lines = func_semiformal.split('\n')
                        if len(func_lines) > 1:
                            # First line is function definition, rest are body
                            func_def_line = func_lines[0]
                            body_lines = func_lines[1:]
                            # Add 4-space indentation to body lines (if not already indented)
                            indented_body = []
                            for body_line in body_lines:
                                if body_line.strip():  # Non-empty line
                                    # Check if already indented (starts with spaces)
                                    if not body_line.startswith(' '):
                                        indented_body.append('    ' + body_line)
                                    else:
                                        indented_body.append(body_line)
                                else:
                                    indented_body.append(body_line)  # Keep empty lines as-is
                            func_semiformal = func_def_line + '\n' + '\n'.join(indented_body)
                        
                        # Find the call site in semiformal spec
                        insert_line = None
                        
                        # First try to find in parsed nodes (semiformal spec)
                        if func_name in func_call_lines:
                            # Use the first call site found
                            insert_line = func_call_lines[func_name][0][0]
                        else:
                            # Fallback: try to find in Python code and map back
                            # Find the Python call line, then try to find corresponding semiformal line
                            if func_name in python_call_sites:
                                python_call_line = python_call_sites[func_name][0]
                                # Try to find a mapped node at this Python line
                                for node_id, mapping_info in mapping.items():
                                    if mapping_info.get('status') == 'mapped':
                                        primary_line = mapping_info.get('primary_line', 0)
                                        if primary_line == python_call_line:
                                            # Find the corresponding semiformal node
                                            sf_node = next(
                                                (n for n in (parsed_nodes or []) if n.get('id') == node_id),
                                                None
                                            )
                                            if sf_node:
                                                insert_line = sf_node.get('line', 0)
                                                break
                        
                        # If we found an insert line, use it; otherwise append at end (None means append)
                        # Check if this function already exists as a stub (needs replacement vs insertion)
                        if func_name in existing_stub_functions:
                            # This function exists - mark for replacement
                            start_line, end_line = existing_stub_functions[func_name]
                            inferred_replacements.append({
                                'type': 'function_body_replacement',
                                'function_name': func_name,
                                'code': func_semiformal,
                                'replace_start_line': start_line,
                                'replace_end_line': end_line,
                                'python_lineno': func_start_line
                            })
                        else:
                            # New function - mark for insertion
                            inferred_insertions.append({
                                'type': 'function_definition',
                                'code': func_semiformal,
                                'insert_line': insert_line,  # None means append at end
                                'func_name': func_name,
                                'python_lineno': func_start_line
                            })
        
        # IMPORTANT: Check for function calls in semiformal spec that don't have definitions
        # Create stub functions for these missing definitions
        defined_functions = set()
        
        # Collect all function definitions in the generated code
        for node in ast.walk(code_ast):
            if isinstance(node, ast.FunctionDef):
                defined_functions.add(node.name)
        
        # Also check if function definitions exist in the semiformal spec (parsed_nodes)
        if parsed_nodes:
            for sf_node in parsed_nodes:
                if sf_node.get('type') == 'function_def':
                    func_name = sf_node.get('value', sf_node.get('content'))
                    if func_name:
                        defined_functions.add(func_name)
        
        # Find all function calls that don't have definitions
        called_functions = set()
        for func_name in func_call_lines.keys():
            if func_name not in defined_functions:
                called_functions.add(func_name)
        
        # Create stub functions for missing definitions
        # Each stub should have at least one inferred line
        for func_name in called_functions:
            # Skip if we already have an insertion for this function
            if any(ins['func_name'] == func_name for ins in inferred_insertions):
                continue
            
            # Get the call site from func_call_lines
            if func_name in func_call_lines:
                call_line, call_node = func_call_lines[func_name][0]
                
                # Extract arguments from the call node if available
                args = call_node.get('args', []) if isinstance(call_node, dict) else []
                
                # Try to infer parameter names from the call
                # For now, use generic parameter names or extract from call
                params = []
                if args:
                    # Try to extract argument expressions
                    for i, arg in enumerate(args):
                        if isinstance(arg, dict):
                            arg_value = arg.get('value', arg.get('content', f'arg{i}'))
                            # Clean up the argument name (remove special chars, keep alphanumeric)
                            param_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in str(arg_value))
                            if param_name and param_name[0].isdigit():
                                param_name = 'arg_' + param_name
                            params.append(param_name if param_name else f'arg{i}')
                        else:
                            params.append(f'arg{i}')
                else:
                    # No arguments provided, use generic 'data' parameter
                    params = ['data']
                
                params_str = ', '.join(params)
                
                # Create a stub function with at least one inferred line
                # Use a generic placeholder that describes what the function should do
                stub_body = f"    result = {func_name} implementation"
                stub_code = f"def {func_name}({params_str}):\n{stub_body}"
                
                inferred_insertions.append({
                    'code': stub_code,
                    'insert_line': call_line,  # Insert above the call site
                    'func_name': func_name
                })
        
        # Also extract any lines with #< annotations (inferred code) that are NOT in function bodies
        # These might be inside function bodies whose definitions were mapped, or standalone lines
        # Group lines into code blocks to handle multi-line structures (for loops, with blocks, etc.)
        inferred_lines = []
        inferred_lines_by_func = {}  # func_name -> list of lines
        
        # First pass: identify all lines with #< and group them into blocks
        inferred_line_numbers = []
        for line_num, line in enumerate(code_lines, start=1):
            if '#<' in line and line_num not in function_body_lines:
                inferred_line_numbers.append(line_num)
        
        # Second pass: group consecutive lines that form code blocks
        # Use AST to detect block structures (for, while, with, if, etc.)
        blocks_to_process = []  # List of (start_line, end_line, block_lines)
        
        i = 0
        while i < len(inferred_line_numbers):
            line_num = inferred_line_numbers[i]
            line = code_lines[line_num - 1]
            
            # Check if this line starts a block structure (for, while, with, if, etc.)
            stripped = line.lstrip()
            is_block_start = any(stripped.startswith(kw + ' ') or stripped.startswith(kw + ':') 
                                for kw in ['for', 'while', 'with', 'if', 'elif', 'else', 'try', 'except', 'finally'])
            
            if is_block_start:
                # This line starts a block - find all lines in this block
                block_indent = len(line) - len(stripped)
                block_lines = [line_num]
                
                # Look ahead for lines that belong to this block
                # They must be consecutive inferred lines with greater indentation
                j = i + 1
                while j < len(inferred_line_numbers):
                    next_line_num = inferred_line_numbers[j]
                    next_line = code_lines[next_line_num - 1]
                    next_indent = len(next_line) - len(next_line.lstrip())
                    
                    # Check if next line is part of the block (must have greater indentation)
                    # and must be immediately consecutive or within a few lines
                    if next_indent > block_indent and next_line_num - block_lines[-1] <= 3:
                        block_lines.append(next_line_num)
                        j += 1
                    else:
                        break
                
                # If we found block body lines, group them together
                if len(block_lines) > 1:
                    blocks_to_process.append((block_lines[0], block_lines[-1], block_lines))
                    i = j  # Skip all lines in this block
                else:
                    # Single line block (just the header) - process normally
                    blocks_to_process.append((line_num, line_num, [line_num]))
                    i += 1
            else:
                # Not a block start - process as single line
                blocks_to_process.append((line_num, line_num, [line_num]))
                i += 1
        
        # Third pass: convert blocks to semiformal
        for start_line, end_line, block_line_nums in blocks_to_process:
            # Extract all code and annotations from the block
            block_code_lines = []
            block_annotations = []
            base_indent = None
            
            for line_num in block_line_nums:
                line = code_lines[line_num - 1]
                
                # Extract code and annotation
                inferred_idx = line.find('#<')
                if inferred_idx != -1:
                    code_part = line[:inferred_idx].rstrip()
                    annotation_part = line[inferred_idx + 2:].strip()
                    
                    block_code_lines.append(code_part)
                    if annotation_part:
                        block_annotations.append(annotation_part)
                    
                    # Track base indentation (from first line)
                    if base_indent is None:
                        base_indent = len(line) - len(line.lstrip())
            
            # Combine annotations (if multiple, join them)
            combined_annotation = ' '.join(block_annotations) if block_annotations else None
            
            # Convert block to semiformal format
            if len(block_line_nums) == 1:
                # Single line - use existing logic
                inferred_line = self._inferred_line_to_semiformal(
                    code_lines[block_line_nums[0] - 1], 
                    block_line_nums[0], 
                    code_ast
                )
            else:
                # Multi-line block - create block-level semiformal
                # For blocks, we want to keep the structure but use the annotation for the body
                first_line = block_code_lines[0].strip()
                
                # Check if first line is a block header (ends with : or contains keywords)
                if first_line.endswith(':'):
                    # Block structure like "for col in data.columns:"
                    # Create semiformal as: "for col in data.columns:\n    <annotation>"
                    if combined_annotation:
                        inferred_line = f"{first_line}\n    {combined_annotation}"
                    else:
                        # No annotation - just use code as-is
                        inferred_line = '\n'.join(block_code_lines)
                else:
                    # Not a typical block - just concatenate with annotations
                    if combined_annotation:
                        # Use last line's LHS if it's an assignment
                        last_code = block_code_lines[-1].strip()
                        if '=' in last_code:
                            lhs = last_code.split('=')[0].strip()
                            inferred_line = f"{lhs} = {combined_annotation}"
                        else:
                            inferred_line = combined_annotation
                    else:
                        inferred_line = '\n'.join(block_code_lines)
            
            if inferred_line:
                # Find which function this block belongs to (if any)
                func_name = None
                for node in ast.walk(code_ast):
                    if isinstance(node, ast.FunctionDef):
                        func_start = getattr(node, 'lineno', 0)
                        if func_start > 0:
                            func_end = func_start
                            for child in ast.walk(node):
                                if hasattr(child, 'lineno') and child.lineno > func_start:
                                    func_end = max(func_end, child.lineno)
                            
                            if func_start <= start_line <= func_end:
                                func_name = node.name
                                break
                
                if func_name:
                    # This block is inside a function - group it
                    original_indent = base_indent if base_indent is not None else 0
                    if func_name not in inferred_lines_by_func:
                        inferred_lines_by_func[func_name] = []
                    # Store with indentation info
                    inferred_lines_by_func[func_name].append((start_line, inferred_line, original_indent))
                else:
                    # Standalone block
                    inferred_lines.append((start_line, inferred_line))
        
        # For each function with inferred lines, create a function definition insertion
        for func_name, lines_info in inferred_lines_by_func.items():
            # Check if we already have an insertion for this function (from unmapped function defs)
            existing = next((i for i in inferred_insertions if i['func_name'] == func_name), None)
            if existing:
                # Already have this function - skip to avoid duplicates
                continue
            
            # Sort by line number
            lines_info.sort(key=lambda x: x[0])
            # Extract lines with their indentation
            func_body_lines = []
            for line_num, inferred_line, original_indent in lines_info:
                # Use original indentation if present and reasonable, otherwise use 4 spaces
                if original_indent > 0 and original_indent <= 20:  # Reasonable indentation limit
                    func_body_lines.append(' ' * original_indent + inferred_line)
                else:
                    func_body_lines.append('    ' + inferred_line)
            
            # Try to find the function definition to get signature
            func_def = None
            for node in ast.walk(code_ast):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    func_def = node
                    break
            
            if func_def:
                # Build function definition with inferred body
                params = [arg.arg for arg in func_def.args.args]
                params_str = ', '.join(params)
                func_code_lines = [f"def {func_name}({params_str}):"]
                func_code_lines.extend(func_body_lines)
                func_code = '\n'.join(func_code_lines)
                
                # Find insert line (same logic as for unmapped functions)
                insert_line = None
                if func_name in func_call_lines:
                    insert_line = func_call_lines[func_name][0][0]
                elif func_name in python_call_sites:
                    python_call_line = python_call_sites[func_name][0]
                    for node_id, mapping_info in mapping.items():
                        if mapping_info.get('status') == 'mapped':
                            primary_line = mapping_info.get('primary_line', 0)
                            if primary_line == python_call_line:
                                sf_node = next(
                                    (n for n in (parsed_nodes or []) if n.get('id') == node_id),
                                    None
                                )
                                if sf_node:
                                    insert_line = sf_node.get('line', 0)
                                    break
                
                inferred_insertions.append({
                    'code': func_code,
                    'insert_line': insert_line,
                    'func_name': func_name
                })
        
        # For standalone inferred lines, group them and add as insertions
        if inferred_lines:
            # Sort by line number
            inferred_lines.sort(key=lambda x: x[0])
            standalone_code = '\n'.join([line for _, line in inferred_lines])
            
            # Try to find where to insert (look for the first line's context)
            insert_line = None
            if inferred_lines:
                first_line_num = inferred_lines[0][0]
                # Try to find a mapped node near this line
                for node_id, mapping_info in mapping.items():
                    if mapping_info.get('status') == 'mapped':
                        primary_line = mapping_info.get('primary_line', 0)
                        # If within 5 lines, use that as reference
                        if abs(primary_line - first_line_num) <= 5:
                            sf_node = next(
                                (n for n in (parsed_nodes or []) if n.get('id') == node_id),
                                None
                            )
                            if sf_node:
                                insert_line = sf_node.get('line', 0)
                                break
            
            # Add as a single insertion (no func_name, use a unique identifier)
            inferred_insertions.append({
                'code': standalone_code,
                'insert_line': insert_line,
                'func_name': f'__standalone_{first_line_num if inferred_lines else 0}'
            })
        
        # Combine all inferred code (for backward compatibility)
        all_inferred_code = []
        for insertion in inferred_insertions:
            all_inferred_code.append(insertion['code'])
        
        return {
            'code': '\n\n'.join(all_inferred_code) if all_inferred_code else '',
            'insertions': inferred_insertions,
            'replacements': inferred_replacements
        }
    
    def _function_def_to_semiformal(
        self,
        func_def: ast.FunctionDef,
        code_lines: List[str]
    ) -> Optional[str]:
        """
        Convert a function definition to semiformal format.
        
        Example:
            def preprocessing(df):  #> preprocessing
                df = df.dropna()  #< drop na
                return df
        
        Converts to:
            def preprocessing(df):
                df = drop na
                return df
        """
        func_start_line = getattr(func_def, 'lineno', 0)
        if func_start_line == 0:
            return None
        
        # Get function signature
        params = [arg.arg for arg in func_def.args.args]
        params_str = ', '.join(params)
        func_name = func_def.name
        
        # Extract function body lines
        body_lines = []
        func_end_line = func_start_line
        
        # Find the end of the function (next statement at same or lower indentation)
        for node in ast.walk(func_def):
            if hasattr(node, 'lineno') and node.lineno > func_start_line:
                func_end_line = max(func_end_line, node.lineno)
        
        # Build semiformal representation
        semiformal_lines = [f"def {func_name}({params_str}):"]
        
        # Process body lines - use AST to get actual body statements
        # This is more reliable than line-by-line parsing
        body_statements = []
        for stmt in func_def.body:
            if isinstance(stmt, (ast.Pass, ast.Ellipsis)):
                continue
            
            # Get line number for this statement
            stmt_line = getattr(stmt, 'lineno', func_start_line + 1)
            if stmt_line <= func_start_line:
                continue
            
            # Check if this statement's line has #< annotation
            if stmt_line <= len(code_lines):
                line = code_lines[stmt_line - 1]
                if '#<' in line:
                    inferred_line = self._inferred_line_to_semiformal(line, stmt_line, None)
                    if inferred_line:
                        # Extract indentation from original line
                        indent = len(line) - len(line.lstrip())
                        # Ensure at least 4 spaces for function body
                        if indent == 0:
                            indent = 4
                        semiformal_lines.append(' ' * indent + inferred_line)
                        continue
            
            # For statements without #<, skip them - they should have #< annotations
            # Only include simple return statements without values
            try:
                if isinstance(stmt, ast.Return) and stmt.value is None:
                    # Simple return without value
                    semiformal_lines.append('    return')
                # Skip all other statements without #< - they should have annotations
            except:
                pass
        
        # Fallback: if AST approach didn't work, use line-by-line
        if len(semiformal_lines) == 1:  # Only function definition line
            for line_num in range(func_start_line + 1, min(func_end_line + 1, len(code_lines) + 1)):
                if line_num > len(code_lines):
                    break
                
                line = code_lines[line_num - 1]
                
                # Skip empty lines and docstrings
                stripped = line.strip()
                if not stripped or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                
                # Only process lines with #< annotation in fallback mode
                if '#<' in line:
                    inferred_line = self._inferred_line_to_semiformal(line, line_num, None)
                    if inferred_line:
                        # Extract indentation from original line
                        indent = len(line) - len(line.lstrip())
                        # Ensure at least 4 spaces for function body
                        if indent == 0:
                            indent = 4
                        semiformal_lines.append(' ' * indent + inferred_line)
        
        return '\n'.join(semiformal_lines)
    
    def extract_function_signatures(self, code_text: str) -> Dict[str, Dict[str, Any]]:
        """
        Extract function signatures from generated Python code.
        
        Returns a mapping of function_name -> signature info for syncing with semiformal stubs.
        
        Example return:
        {
            'load_dataset': {
                'name': 'load_dataset',
                'params': ['source'],
                'signature': 'load_dataset(source)'
            }
        }
        """
        signatures = {}
        
        try:
            tree = ast.parse(code_text)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_name = node.name
                    params = [arg.arg for arg in node.args.args]
                    params_str = ', '.join(params)
                    
                    signatures[func_name] = {
                        'name': func_name,
                        'params': params,
                        'signature': f"{func_name}({params_str})",
                        'lineno': node.lineno
                    }
        except:
            pass
        
        return signatures
    
    def _inferred_line_to_semiformal(
        self,
        line: str,
        line_num: int,
        code_ast: Optional[ast.Module]
    ) -> Optional[str]:
        """
        Convert a line with #< annotation to semiformal format.
        
        Example:
            df = df.dropna()  #< drop na
        Converts to:
            df = drop na
        """
        # Extract the #< annotation
        inferred_idx = line.find('#<')
        if inferred_idx == -1:
            return None
        
        code_part = line[:inferred_idx].rstrip()
        annotation_part = line[inferred_idx + 2:].strip()
        
        # Parse the annotation (can have multiple parts separated by ; or #)
        inferred_phrases = []
        for part in re.split(r'[;#]', annotation_part):
            part = part.strip()
            if part:
                inferred_phrases.append(part)
        
        if not inferred_phrases:
            return None
        
        # Try to parse the code part to understand the structure
        try:
            tree = ast.parse(code_part)
            if tree.body:
                stmt = tree.body[0]
                
                if isinstance(stmt, ast.Assign):
                    # Assignment: var = value
                    targets = [ast.unparse(t) for t in stmt.targets]
                    target_str = ', '.join(targets)
                    
                    # Use the first inferred phrase as the RHS
                    rhs = inferred_phrases[0]
                    if len(inferred_phrases) > 1:
                        # Multiple phrases - combine them
                        rhs = ' '.join(inferred_phrases)
                    
                    return f"{target_str} = {rhs}"
                
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    # Function call expression - convert to assignment if it makes sense
                    call = stmt.value
                    if isinstance(call.func, ast.Name):
                        func_name = call.func.id
                        # Use inferred phrase as description
                        rhs = ' '.join(inferred_phrases)
                        # For call expressions, create an assignment pattern
                        return f"{func_name} = {rhs}"
                    elif isinstance(call.func, ast.Attribute):
                        # Method call like df.hist() - extract the target
                        try:
                            target = ast.unparse(call.func.value)
                            method = call.func.attr
                            rhs = ' '.join(inferred_phrases)
                            return f"{target} = {rhs}"
                        except:
                            # If unparse fails, just use inferred phrase
                            return ' '.join(inferred_phrases)
                
                elif isinstance(stmt, ast.Return):
                    # Return statement
                    if inferred_phrases:
                        return f"return {inferred_phrases[0]}"
        except SyntaxError:
            # If parsing fails due to incomplete code, try to extract structure more carefully
            # Don't use simple string splitting as it can produce wrong results
            
            # First, check if code_part looks like it might be complete (has balanced parens/brackets)
            # This helps avoid trying to parse clearly incomplete code
            paren_count = code_part.count('(') - code_part.count(')')
            bracket_count = code_part.count('[') - code_part.count(']')
            brace_count = code_part.count('{') - code_part.count('}')
            
            # If parens/brackets are unbalanced, the code is likely incomplete
            # In this case, be very conservative about what we extract
            if abs(paren_count) > 2 or abs(bracket_count) > 2 or abs(brace_count) > 2:
                # Code is clearly incomplete - just use inferred phrase
                if inferred_phrases:
                    return ' '.join(inferred_phrases)
                return None
            
            # Try to extract assignment pattern more carefully
            if '=' in code_part:
                # Find the first = that's not inside quotes or function calls
                equals_pos = -1
                in_quotes = False
                quote_char = None
                paren_depth = 0
                
                for i, char in enumerate(code_part):
                    if char in ('"', "'") and (i == 0 or code_part[i-1] != '\\'):
                        if not in_quotes:
                            in_quotes = True
                            quote_char = char
                        elif char == quote_char:
                            in_quotes = False
                            quote_char = None
                    elif not in_quotes:
                        if char == '(':
                            paren_depth += 1
                        elif char == ')':
                            paren_depth -= 1
                        elif char == '=' and paren_depth == 0:
                            equals_pos = i
                            break
                
                if equals_pos > 0:
                    lhs = code_part[:equals_pos].strip()
                    # Validate that LHS looks reasonable (not empty, not too long, has valid identifier)
                    if lhs and len(lhs) < 100 and (lhs[0].isalpha() or lhs[0] == '_' or '.' in lhs):
                        # For RHS, use inferred phrase instead of trying to parse incomplete code
                        rhs = ' '.join(inferred_phrases)
                        return f"{lhs} = {rhs}"
            
            # If we can't extract assignment, just return the inferred phrase as a statement
            # This is safer than trying to parse incomplete code
            if inferred_phrases:
                return ' '.join(inferred_phrases)
        
        except Exception:
            # Any other error - fall back to using inferred phrases only
            if inferred_phrases:
                return ' '.join(inferred_phrases)
        
        return None
    
    def _python_line_to_semiformal(self, line: str, line_num: int) -> Optional[str]:
        """
        Convert a Python line to semiformal format (simple cases).
        
        This is a fallback for lines without #< annotations.
        """
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            return None
        
        try:
            tree = ast.parse(stripped)
            if tree.body:
                stmt = tree.body[0]
                
                if isinstance(stmt, ast.Assign):
                    # Simple assignment - keep as is for now
                    return stripped
                
                elif isinstance(stmt, ast.Return):
                    return stripped
        except:
            pass
        
        return stripped