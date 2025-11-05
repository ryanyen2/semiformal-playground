# Semiformal Programming Playground

A bidirectional programming environment for semiformal Python code with CodeMirror.

## Overview

This project enables users to write incomplete Python code with:
- Function identifiers without declarations
- Variables without concrete assigned values
- Natural language expressions

The system automatically:
- Parses incomplete code using AST analysis
- Creates stub declarations with placeholders
- Generates complete code using LLM (GPT-4o)
- Maintains bidirectional synchronization between specs and generated code

## Project Structure

```
semiformal-playground/
├── backend/           # Python FastAPI backend
│   ├── main.py       # API server
│   ├── parser.py     # AST-based incomplete code parser
│   ├── generator.py  # LLM code generation
│   └── sync.py       # Bidirectional sync logic
├── frontend/         # TypeScript + CodeMirror frontend
│   └── src/
│       ├── editor.ts # CodeMirror setup
│       ├── decorations.ts # Code decorations
│       └── sync.ts   # Sync logic
└── requirements.txt  # Python dependencies
```

## Prerequisites

- Python 3.8 or higher
- Node.js 18 or higher
- OpenAI API key (for code generation)

## Setup

### Quick Start

1. **Clone and navigate to the project**
   ```bash
   cd semiformal-playground
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your OpenAI API key
   ```

3. **Start the backend** (in one terminal)
   ```bash
   ./start-backend.sh
   ```

4. **Start the frontend** (in another terminal)
   ```bash
   ./start-frontend.sh
   ```

5. **Open your browser**
   Navigate to http://localhost:3000

### Manual Setup

#### Backend
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Run the server
cd backend
python main.py
```

The backend will start on http://localhost:8000

#### Frontend
```bash
cd frontend
npm install
npm run dev
```

The frontend will start on http://localhost:3000

## Features

### Spec → Code Synchronization
- Parameter additions → direct code update + body regeneration
- Function renames → downstream call updates (no LLM)
- Statement insertions → dependency-aware placement
- Comments/incomplete code → added as constraints + regeneration

### Code → Spec Synchronization
- Edited blocks surface back to semiformal code
- Line-level granularity for precise updates

## Usage Guide

### Basic Workflow

1. **Write Semiformal Code**
   Write incomplete Python code in the left editor. You can use:
   - Function calls without definitions
   - Variables with natural language descriptions
   - Incomplete assignments with `...`

2. **Parse the Code**
   Click "Parse" to analyze incomplete parts. The system will:
   - Identify missing function declarations
   - Detect undefined variables
   - Highlight natural language expressions
   - Insert stub declarations

3. **Generate Complete Code**
   Click "Generate Code" to use LLM to fill in the missing implementations.
   The generated code appears in the right editor.

4. **Edit and Sync**
   - Edit the spec (left): Changes automatically sync to generated code
   - Edit the code (right): Click "Sync to Spec" to update the spec

### Example Usage

#### Example 1: Function Without Declaration

```python
# Write this in the spec editor:
result = calculate_average([1, 2, 3, 4, 5])
print(result)
```

After parsing, a stub will be created:
```python
def calculate_average(arg0):
    ...

result = calculate_average([1, 2, 3, 4, 5])
print(result)
```

After generation, you'll get complete code:
```python
def calculate_average(numbers):
    return sum(numbers) / len(numbers)

result = calculate_average([1, 2, 3, 4, 5])
print(result)
```

#### Example 2: Natural Language Variable

```python
# Write this in the spec editor:
data = load and preprocess the dataset
model = train_model(data)
```

After generation:
```python
data = load_and_preprocess_dataset()  # Generated function
model = train_model(data)
```

#### Example 3: Bidirectional Edits

If you add a parameter to a function in the spec:
```python
def process(data, normalize):  # Added 'normalize' parameter
    ...
```

The system will:
1. Update the function signature in generated code
2. Trigger regeneration to use the new parameter

### Tips

- Use descriptive natural language for better LLM generation
- The system tracks dependencies for intelligent code placement
- Function renames propagate automatically without LLM calls
- Manual code edits can be surfaced back to specs for documentation
