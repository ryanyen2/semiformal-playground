# Semiformal Programming Playground

A bidirectional programming environment for semiformal Python code with CodeMirror and OpenAI.

## Overview

This project enables users to write semiformal Python code mixing:
- **Python code**: Regular Python syntax
- **Natural language**: Plain English descriptions (e.g., `result = load the dataset`)
- **Holes**: `{}` for empty holes, `{hint text}` for hints
- **Placeholders**: Incomplete values that need filling

The system automatically:
- **Parses** semiformal code into intent nodes (auto-debounced, 1 second after typing stops)
- **Generates** complete Python code using OpenAI GPT-4o-mini
- **Decorates** the editor with visual cues for NL, holes, and placeholders
- **Maintains** bidirectional synchronization

## Quick Start

### 1. Set up environment
```bash
# Create .env file with your OpenAI API key
echo "OPENAI_API_KEY=your-key-here" > .env
```

### 2. Start the MVP backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r ../requirements.txt
python mvp_main.py
```

The backend starts on **http://localhost:8001**

### 3. Start the frontend
```bash
cd frontend
npm install
npm run dev
```

The frontend starts on **http://localhost:3000**

## Usage

The UI is designed to be **clean and automatic** with no manual buttons:

### Auto-Parsing (1-second debounce)
- **Type** in the left editor (Semiformal Code)
- **Wait 1 second** - the parser runs automatically
- **See decorations**: Natural language phrases in green italic, holes with dotted underlines

### Generate Python Code (Cmd+S)
- **Press Cmd+S** (or Ctrl+S) in the semiformal editor
- **Python code** is generated in the right editor
- **No buttons needed** - all sync happens automatically

### Visual Decorations
- **Natural language**: Green italic text
- **Holes `{}`**: Yellow dotted underline
- **Holes with hints `{text}`**: Purple dotted underline
- **Placeholders**: Teal left border
- **Cursor mapping**: Blue highlight when cursor is on a node

### Status Indicators
- **Parsing dot**: Yellow pulse while parsing
- **Generating dot**: Purple pulse while generating
- **Ready dot**: Green pulse when idle
- **Status bar**: Shows node count and LLM availability

## Project Structure

```
semiformal-playground/
├── backend/
│   ├── mvp_config.py      # Configuration system
│   ├── mvp_parser.py      # Semiformal → Intent Nodes
│   ├── mvp_generator.py   # Intent Nodes → Python (with OpenAI)
│   ├── mvp_translator.py  # Edit translation
│   ├── mvp_edit.py        # Direct AST operations
│   ├── mvp_editor.py      # Main orchestrator
│   └── mvp_main.py        # FastAPI server (port 8001)
├── frontend/
│   ├── index.html         # Clean UI with no manual buttons
│   └── src/
│       ├── api.ts         # MVP backend API client
│       ├── editor.ts      # CodeMirror setup
│       ├── decorations.ts # Node-based decorations
│       └── index.ts       # Auto-parse + Cmd+S generation
├── EDIT_MAPPING_TABLE.md  # 71 semiformal→Python edit types
├── MVP_ARCHITECTURE.md    # Complete architecture spec
├── test_mvp.py           # MVP test suite
└── test_edge_cases.py    # 31 edge case tests
```

## MVP Implementation Phases

### ✅ Phase 1: Direct AST Edits (36.6% of edits)
- Identifier renames
- Operator changes (+, -, *, /)
- Literal value changes
- Parameter additions/removals
- Statement insertions/deletions

**No LLM needed** - uses Python AST manipulation directly.

### ✅ Phase 2: Placeholder Support (18.3% of edits)
- Add variable to LHS when RHS is unknown
- Incomplete expressions with `None` placeholders
- Mark targets for regeneration

### ✅ Phase 3: Hole Syntax + LLM (35.2% of edits)
- `{}` - Empty hole, LLM fills based on context
- `{hint}` - Hole with hint text for LLM
- Natural language phrases
- Full LLM-based code generation

### 📋 Phase 4-6: Advanced Features (Future)
- Cross-function edits
- Multi-statement NL blocks
- Context-aware regeneration
- Advanced dependency tracking

## Features

### Automatic Bidirectional Sync
- **Semiformal → Python**: Changes automatically update generated code
- **Python → Semiformal**: Edits to Python can propagate back (transient vs semantic)
- **No manual buttons**: Everything happens automatically

### Configuration-Driven
All behavior is configurable via `MVPConfig`:
```python
- LLM model, temperature, max_tokens
- Parser settings (NLP, tokenization)
- Edit type categorization
- Generator validation and retries
```

**No hardcoded assumptions** - works for any domain, not just data science/ML.

### Node Mapping Visualization
- **Cursor tracking**: See which node your cursor is on
- **Highlighting**: Mapped nodes highlighted in blue
- **Console logging**: Node → Python code mappings in dev console

### Comprehensive Edit Support
See `EDIT_MAPPING_TABLE.md` for all **71 semiformal→Python** and **17 Python→semiformal** edit types.

## Examples

### Example 1: Natural Language
```python
# Semiformal (left editor)
data = load the dataset and clean it
result = process(data)

# Generated Python (right editor - after Cmd+S)
data = None  # TODO: Fill this placeholder
result = process(data)
```

### Example 2: Hole Syntax
```python
# Semiformal
x = {calculate the mean of numbers}
y = {}

# With OpenAI API key configured:
x = calculate_mean(numbers)
y = None  # TODO: Fill this placeholder
```

### Example 3: Function Calls Without Definitions
```python
# Semiformal
result = transform(clean(data))
print(result)

# Generated (with stubs)
result = transform(clean(data))
print(result)
```

## Testing

### Run MVP Tests
```bash
python test_mvp.py
```
Tests Phases 1-3 (6 tests total)

### Run Edge Case Tests
```bash
python test_edge_cases.py
```
Comprehensive edge case coverage (31 tests):
- Empty inputs, complex expressions
- NL edge cases, error handling
- Unicode/multi-byte characters
- Large codebases (100 vars, 50 functions)

All **37/37 tests passing** ✓

## Architecture

See `MVP_ARCHITECTURE.md` for complete specification including:
- Intent node types and examples
- Edit type categorization
- Code generation strategies
- Mapping maintenance
- Example walkthrough

## API Endpoints

The MVP backend (`mvp_main.py`) provides:

- `POST /initialize` - Parse semiformal code, generate initial Python
- `POST /edit/semiformal` - Apply semiformal edits
- `POST /edit/python` - Handle Python code edits
- `POST /fill-hole` - Fill a hole using LLM
- `POST /regenerate` - Regenerate code for a target
- `GET /state` - Get current editor state
- `GET /` - Health check + capabilities

## Requirements

- **Python 3.8+**
- **Node.js 18+**
- **OpenAI API key** (optional - LLM features disabled without it)

## Environment Variables

```bash
OPENAI_API_KEY=your-key-here  # Required for LLM features
PORT=8001                      # Optional, defaults to 8001
```

## Development

### Backend Development
```bash
cd backend
python mvp_main.py  # Starts on port 8001
```

### Frontend Development
```bash
cd frontend
npm run dev  # Starts on port 3000, proxies /api to port 8001
```

### Run All Tests
```bash
python test_mvp.py && python test_edge_cases.py
```

## Troubleshooting

### Backend not reachable
- Ensure `mvp_main.py` is running on port 8001
- Check `vite.config.ts` proxy settings

### LLM features not working
- Set `OPENAI_API_KEY` in `.env` file
- Restart the backend after setting the key

### Decorations not showing
- Clear browser cache
- Check browser console for errors
- Ensure auto-parse completed (wait 1 second after typing)

## Contributing

See `EDIT_MAPPING_TABLE.md` for edit type coverage and `MVP_ARCHITECTURE.md` for implementation details.

All contributions should:
- Maintain general-purpose implementation (no domain-specific assumptions)
- Update tests for new features
- Follow configuration-driven architecture
- Document edit types in the mapping table

## License

MIT
