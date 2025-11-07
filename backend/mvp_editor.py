"""
MVP Bidirectional Editor

Main orchestrator that ties together:
- Parser (intent nodes)
- Generator (code generation + mapping)
- Translator (edit translation)
- Direct operations (AST manipulation)
"""

from typing import List, Dict, Any, Optional
from mvp_parser import SemiformalParser, IntentNode, parse_semiformal
from mvp_generator import CodeGenerator, Mapping
from mvp_translator import EditTranslator, Edit, UpdateDecider
from mvp_edit import EditResult


class BidirectionalEditor:
    """
    Main editor orchestrating semiformal ↔ Python synchronization.

    Implements Phases 1-3:
    - Phase 1: Direct AST edits
    - Phase 2: Placeholder support
    - Phase 3: Hole syntax and LLM generation
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize the bidirectional editor.

        Args:
            openai_api_key: OpenAI API key for LLM features
        """
        self.parser = SemiformalParser()
        self.generator = CodeGenerator(openai_api_key)
        self.translator: Optional[EditTranslator] = None
        self.update_decider = UpdateDecider()

        # State
        self.semiformal_code = ""
        self.python_code = ""
        self.intent_nodes: List[IntentNode] = []
        self.mappings: List[Mapping] = []

    def initialize(self, semiformal_code: str) -> Dict[str, Any]:
        """
        Initialize from semiformal code.

        Flow:
        1. Parse semiformal → intent nodes
        2. Generate Python from nodes
        3. Create node→code mappings
        4. Set up translator

        Args:
            semiformal_code: The semiformal Python code

        Returns:
            Dict with python_code, nodes, and mappings
        """
        self.semiformal_code = semiformal_code

        # Step 1: Parse
        self.intent_nodes = self.parser.parse(semiformal_code)

        # Step 2: Generate Python
        self.python_code, self.mappings = self.generator.generate_with_mapping(
            self.intent_nodes,
            context=semiformal_code
        )

        # Step 3: Set up translator
        self.translator = EditTranslator(self.mappings, self.generator)

        return {
            'python_code': self.python_code,
            'nodes': [self._node_to_dict(node) for node in self.intent_nodes],
            'mappings': [self._mapping_to_dict(mapping) for mapping in self.mappings],
            'message': f'Parsed {len(self.intent_nodes)} intent nodes, generated {len(self.python_code.splitlines())} lines'
        }

    def on_semiformal_edit(self, edit: Edit) -> Dict[str, Any]:
        """
        Handle edit to semiformal code.

        Flow:
        1. Translate semiformal edit → Python edit
        2. Apply Python edit
        3. Update mappings if needed

        Args:
            edit: The edit made to semiformal code

        Returns:
            Dict with updated python_code and result info
        """
        if not self.translator:
            return {
                'success': False,
                'message': 'Editor not initialized. Call initialize() first.'
            }

        # Translate to Python edit
        result: EditResult = self.translator.semiformal_to_python(
            edit,
            self.semiformal_code,
            self.python_code
        )

        if result.success:
            # Apply the edit
            self.python_code = result.new_code

            # Update mappings if needed
            if result.needs_regeneration:
                self._handle_regeneration(result.regeneration_targets)

        return {
            'success': result.success,
            'python_code': self.python_code,
            'message': result.message,
            'needs_regeneration': result.needs_regeneration,
            'regeneration_targets': result.regeneration_targets
        }

    def on_python_edit(self, edit: Edit) -> Dict[str, Any]:
        """
        Handle edit to generated Python code.

        Flow:
        1. Decide if should propagate (using UpdateDecider)
        2. If transient: just update Python
        3. If semantic: suggest semiformal update

        Args:
            edit: The edit made to Python code

        Returns:
            Dict with result info and optional semiformal suggestion
        """
        # Decide if should propagate
        should_propagate, strategy = self.update_decider.should_propagate(edit)

        if not should_propagate:
            # Transient change - just note it
            return {
                'success': True,
                'propagate': False,
                'message': 'Transient edit - not propagating to semiformal',
                'edit_type': edit.type
            }

        # Semantic change - should propagate
        # For now, we'll suggest to user rather than auto-propagate
        suggestion = self._generate_semiformal_suggestion(edit)

        return {
            'success': True,
            'propagate': True,
            'message': f'Semantic change detected - suggest updating semiformal',
            'suggestion': suggestion,
            'strategy': strategy
        }

    def apply_direct_edit(
        self,
        edit_type: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Apply a direct edit operation.

        Convenience method for common direct edits.

        Args:
            edit_type: Type of edit (rename, add_param, etc.)
            **kwargs: Edit-specific arguments

        Returns:
            Dict with result info
        """
        edit = Edit(
            type=edit_type,
            location=kwargs.get('location', ''),
            content=kwargs.get('content', ''),
            old_content=kwargs.get('old_content'),
            line=kwargs.get('line'),
            metadata=kwargs.get('metadata', {})
        )

        return self.on_semiformal_edit(edit)

    def fill_hole(
        self,
        line_num: int,
        hint: str = "",
        target_var: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fill a hole on a specific line.

        Phase 3: Hole filling

        Args:
            line_num: Line number with the hole
            hint: Optional hint for LLM
            target_var: Variable being assigned to

        Returns:
            Dict with filled code
        """
        edit = Edit(
            type='hole_fill',
            location=str(line_num),
            content=hint,
            line=line_num,
            metadata={'target_var': target_var}
        )

        if not self.translator:
            return {
                'success': False,
                'message': 'Editor not initialized'
            }

        result = self.translator.semiformal_to_python(
            edit,
            self.semiformal_code,
            self.python_code
        )

        if result.success:
            self.python_code = result.new_code

        return {
            'success': result.success,
            'python_code': self.python_code,
            'message': result.message
        }

    def regenerate(self, target: Optional[str] = None) -> Dict[str, Any]:
        """
        Regenerate code for a specific target or entire code.

        Args:
            target: Optional function name or section to regenerate

        Returns:
            Dict with regenerated code
        """
        # Re-parse semiformal code
        self.intent_nodes = self.parser.parse(self.semiformal_code)

        # Re-generate Python
        self.python_code, self.mappings = self.generator.generate_with_mapping(
            self.intent_nodes,
            context=self.semiformal_code
        )

        # Update translator
        self.translator = EditTranslator(self.mappings, self.generator)

        return {
            'success': True,
            'python_code': self.python_code,
            'message': f'Regenerated {"entire code" if not target else target}'
        }

    def get_state(self) -> Dict[str, Any]:
        """
        Get current editor state.

        Returns:
            Dict with all current state information
        """
        return {
            'semiformal_code': self.semiformal_code,
            'python_code': self.python_code,
            'nodes': [self._node_to_dict(node) for node in self.intent_nodes],
            'mappings': [self._mapping_to_dict(mapping) for mapping in self.mappings],
            'has_llm': self.generator.client is not None
        }

    def _handle_regeneration(self, targets: List[str]):
        """Handle regeneration of specific targets"""
        # For now, regenerate entire code
        # Production would regenerate only affected sections
        if targets:
            print(f"Regeneration needed for: {', '.join(targets)}")
            # TODO: Implement targeted regeneration

    def _generate_semiformal_suggestion(self, edit: Edit) -> str:
        """
        Generate a suggestion for updating semiformal code.

        Uses LLM to summarize Python change in natural language.
        """
        if not self.generator.client:
            return f"# TODO: Update semiformal for edit: {edit.type}"

        # For now, simple suggestion
        return f"# Suggested: {edit.type} - {edit.content}"

    def _node_to_dict(self, node: IntentNode) -> Dict[str, Any]:
        """Convert IntentNode to dict for JSON serialization"""
        return {
            'id': node.id,
            'type': node.type,
            'content': node.content,
            'span': node.span,
            'dependencies': node.dependencies,
            'metadata': node.metadata
        }

    def _mapping_to_dict(self, mapping: Mapping) -> Dict[str, Any]:
        """Convert Mapping to dict for JSON serialization"""
        return {
            'node_id': mapping.node_id,
            'slices': [
                {
                    'code': s.code,
                    'line_start': s.line_start,
                    'line_end': s.line_end
                }
                for s in mapping.slices
            ],
            'confidence': mapping.confidence,
            'generation_method': mapping.generation_method
        }


# Convenience functions for common operations

def create_editor(openai_api_key: Optional[str] = None) -> BidirectionalEditor:
    """Create and return a new BidirectionalEditor instance"""
    return BidirectionalEditor(openai_api_key)


def parse_and_generate(
    semiformal_code: str,
    openai_api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    One-shot parse and generate from semiformal code.

    Args:
        semiformal_code: The semiformal Python code
        openai_api_key: Optional OpenAI API key

    Returns:
        Dict with python_code and metadata
    """
    editor = BidirectionalEditor(openai_api_key)
    return editor.initialize(semiformal_code)
