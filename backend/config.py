"""
Configuration for MVP implementation

This module contains all configurable parameters and constants
to avoid hardcoded values throughout the codebase.
"""

from typing import List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    """Configuration for LLM (OpenAI) integration"""
    model: str = "gpt-5-mini"  # Model to use
    temperature: float = 0.1  # Temperature for generation
    max_tokens: int = 2048  # Max tokens for completion
    timeout: int = 30  # Timeout in seconds


@dataclass
class ParserConfig:
    """Configuration for semiformal parser"""
    # Whether to use NLP for phrase segmentation (future enhancement)
    use_nlp: bool = False

    # Fallback: treat entire RHS as single token if no keywords found
    fallback_to_single_token: bool = True

    # Maximum node depth for expression parsing
    max_expression_depth: int = 10


@dataclass
class EditTypeConfig:
    """Configuration for edit type categorization"""

    # Phase 1: Direct AST edits (no LLM needed)
    direct_edit_types: List[str] = field(default_factory=lambda: [
        'identifier_rename',
        'function_rename',
        'parameter_rename',
        'operator_change',
        'literal_change',
        'parameter_add',
        'parameter_remove',
        'parameter_reorder',
        'statement_insert',
        'statement_delete',
        'argument_reorder',
        'import_add',
        'import_remove',
    ])

    # Phase 2: Placeholder support
    placeholder_edit_types: List[str] = field(default_factory=lambda: [
        'identifier_add_lhs',
        'argument_add',
        'variable_incomplete',
        'function_stub',
    ])

    # Phase 3: Hole filling
    hole_edit_types: List[str] = field(default_factory=lambda: [
        'hole_fill',
        'hole_add_hint',
        'hole_modify_hint',
    ])

    # LLM-required edits
    llm_edit_types: List[str] = field(default_factory=lambda: [
        'nl_phrase_add',
        'nl_phrase_modify',
        'add_function_body',
        'extract_function',
        'inline_function',
    ])

    # Transient edits (don't propagate Python → Semiformal)
    transient_patterns: List[str] = field(default_factory=lambda: [
        'constant_tweak',
        'variable_rename_internal',
        'code_refactoring',
        'debug_print',
        'optimize_expression',
        'reorder_imports',
        'add_type_hint',
        'format_code',
        'python_line_edit',
    ])

    # Semantic changes (must propagate Python → Semiformal)
    semantic_patterns: List[str] = field(default_factory=lambda: [
        'add_function',
        'change_function_logic',
        'add_dependency',
        'change_return_value',
        'add_class',
        'modify_algorithm',
    ])


@dataclass
class GeneratorConfig:
    """Configuration for code generation"""

    # Whether to include node annotations in generated code
    include_node_annotations: bool = True

    # Confidence threshold for LLM-generated code
    llm_confidence_threshold: float = 0.7

    # Whether to fallback to placeholders if LLM fails
    fallback_to_placeholder: bool = True

    # Maximum retries for LLM calls
    max_llm_retries: int = 3

    # Whether to validate generated code before returning
    validate_generated_code: bool = True


@dataclass
class MVPConfig:
    """Main configuration for MVP"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    edit_types: EditTypeConfig = field(default_factory=EditTypeConfig)
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'MVPConfig':
        """Create config from dictionary"""
        return cls(
            llm=LLMConfig(**config_dict.get('llm', {})),
            parser=ParserConfig(**config_dict.get('parser', {})),
            edit_types=EditTypeConfig(**config_dict.get('edit_types', {})),
            generator=GeneratorConfig(**config_dict.get('generator', {}))
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            'llm': {
                'model': self.llm.model,
                'temperature': self.llm.temperature,
                'max_tokens': self.llm.max_tokens,
                'timeout': self.llm.timeout,
            },
            'parser': {
                'use_nlp': self.parser.use_nlp,
                'fallback_to_single_token': self.parser.fallback_to_single_token,
                'max_expression_depth': self.parser.max_expression_depth,
            },
            'edit_types': {
                'direct_edit_types': self.edit_types.direct_edit_types,
                'placeholder_edit_types': self.edit_types.placeholder_edit_types,
                'hole_edit_types': self.edit_types.hole_edit_types,
                'llm_edit_types': self.edit_types.llm_edit_types,
                'transient_patterns': self.edit_types.transient_patterns,
                'semantic_patterns': self.edit_types.semantic_patterns,
            },
            'generator': {
                'include_node_annotations': self.generator.include_node_annotations,
                'llm_confidence_threshold': self.generator.llm_confidence_threshold,
                'fallback_to_placeholder': self.generator.fallback_to_placeholder,
                'max_llm_retries': self.generator.max_llm_retries,
                'validate_generated_code': self.generator.validate_generated_code,
            }
        }


# Default configuration instance
DEFAULT_CONFIG = MVPConfig()
