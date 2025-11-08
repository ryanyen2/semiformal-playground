/**
 * Main entry point for the semiformal programming playground.
 *
 * Features:
 * - Auto-parse with 1-second debounce
 * - Cmd/Ctrl+S to generate code
 * - Bidirectional sync
 * - Cursor-based node mapping visualization
 */

import { EditorView } from '@codemirror/view'
import { createEditor, getEditorContent } from './editor'
import {
  nodeDecorationsField,
  nodesStateField,
  cursorMappingStateField,
  mappingsStateField,
  pythonLineStateField,
  pythonLineDecorationsField,
  updateNodeDecorations,
  updateMappingDecorations,
  updateCursorMapping,
  updatePythonLineHighlight,
  findNodeAtCursor,
  findMappingForNode
} from './decorations'
import { api, IntentNode, NodeMapping } from './api'

// Initial example code
const EXAMPLE_SPEC = `# Semiformal Python Example
# Type to parse automatically (debounced)
# Press Cmd+S to generate Python code

# Example 1: Natural language
result = load the dataset and process it

# Example 2: Function call
output = transform(result)

# Example 3: Hole syntax
x = {}
y = {split data into train and test}

print(output)
`

// Application state
let specEditor: EditorView
let codeEditor: EditorView
let parseTimeout: number | null = null
let isGenerating = false
let isParsing = false

// Current state
let currentNodes: IntentNode[] = []
let currentMappings: NodeMapping[] = []
let hasLLM = false

/**
 * UI status helpers
 */
function setSpecStatus(text: string, className: '' | 'parsing' | 'generating' = '') {
  const dot = document.getElementById('spec-status-dot')
  const status = document.getElementById('spec-status-text')
  if (dot && status) {
    dot.className = `status-dot ${className}`
    status.textContent = text
  }
}

function setCodeStatus(text: string, className: '' | 'parsing' | 'generating' = '') {
  const dot = document.getElementById('code-status-dot')
  const status = document.getElementById('code-status-text')
  if (dot && status) {
    dot.className = `status-dot ${className}`
    status.textContent = text
  }
}

function setStatusMessage(message: string, type: '' | 'parsing' | 'generating' | 'error' | 'success' = '') {
  const statusBar = document.getElementById('status-bar')
  const statusMessage = document.getElementById('status-message')

  if (statusBar && statusMessage) {
    statusBar.className = `status-bar ${type}`
    statusMessage.textContent = message
  }
}

function setNodeCount(count: number) {
  const nodeCount = document.getElementById('node-count')
  if (nodeCount) {
    nodeCount.textContent = `${count} node${count !== 1 ? 's' : ''}`
  }
}

function setLLMStatus(available: boolean) {
  const llmStatus = document.getElementById('llm-status')
  if (llmStatus) {
    llmStatus.textContent = available ? 'LLM: available' : 'LLM: not configured'
    llmStatus.style.color = available ? '#4ec9b0' : '#858585'
  }
}

/**
 * Parse semiformal code (debounced)
 */
async function parseCode(semiformalCode: string) {
  if (isParsing) return
  isParsing = true

  try {
    setSpecStatus('Parsing...', 'parsing')
    setStatusMessage('Parsing semiformal code...', 'parsing')

    const result = await api.initialize(semiformalCode)

    currentNodes = result.nodes
    currentMappings = result.mappings

    // Update Python code editor with generated code
    codeEditor.dispatch({
      changes: {
        from: 0,
        to: codeEditor.state.doc.length,
        insert: result.python_code
      }
    })

    // Update decorations
    updateNodeDecorations(specEditor, result.nodes)
    updateMappingDecorations(specEditor, result.mappings)

    // Update UI
    setNodeCount(result.nodes.length)
    setSpecStatus('Parsed', '')
    setCodeStatus('Generated', '')
    setStatusMessage(result.message, 'success')

    console.log('Parse result:', result)
  } catch (error) {
    console.error('Parse error:', error)
    setSpecStatus('Parse error', '')
    setStatusMessage(
      `Parse error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  } finally {
    isParsing = false
  }
}

/**
 * Generate Python code (Cmd+S)
 */
async function generateCode() {
  if (isGenerating || isParsing) return
  isGenerating = true

  try {
    const semiformalCode = getEditorContent(specEditor)

    setCodeStatus('Generating...', 'generating')
    setStatusMessage('Generating Python code...', 'generating')

    const result = await api.initialize(semiformalCode)

    // Update code editor
    codeEditor.dispatch({
      changes: {
        from: 0,
        to: codeEditor.state.doc.length,
        insert: result.python_code
      }
    })

    currentNodes = result.nodes
    currentMappings = result.mappings

    // Update decorations
    updateNodeDecorations(specEditor, result.nodes)
    updateMappingDecorations(specEditor, result.mappings)

    // Update UI
    setCodeStatus('Generated', '')
    setStatusMessage(result.message, 'success')
    setNodeCount(result.nodes.length)

    console.log('Generation result:', result)
  } catch (error) {
    console.error('Generation error:', error)
    setCodeStatus('Generation error', '')
    setStatusMessage(
      `Generation error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  } finally {
    isGenerating = false
  }
}

/**
 * Handle cursor movement to highlight mapped nodes
 */
function handleCursorMove(view: EditorView) {
  const cursorPos = view.state.selection.main.head
  const line = view.state.doc.lineAt(cursorPos)
  const lineNum = line.number
  const colNum = cursorPos - line.from

  // Find node at cursor
  const nodeIndex = findNodeAtCursor(currentNodes, lineNum, colNum)

  // Update cursor mapping
  updateCursorMapping(view, nodeIndex)

  // If there's a mapping, highlight the corresponding Python code
  if (nodeIndex !== null) {
    const mapping = findMappingForNode(currentMappings, nodeIndex)
    if (mapping) {
      console.log(`Cursor on node #${nodeIndex}:`, currentNodes[nodeIndex])
      console.log(`Maps to Python line ${mapping.code_line}:`, mapping.code_snippet)

      // Highlight the Python line in the code editor
      updatePythonLineHighlight(codeEditor, mapping.code_line)
    } else {
      // Clear Python line highlight if no mapping
      updatePythonLineHighlight(codeEditor, null)
    }
  } else {
    // Clear Python line highlight if no node
    updatePythonLineHighlight(codeEditor, null)
  }
}

/**
 * Handle spec editor changes with debouncing
 */
function handleSpecChange() {
  // Clear existing timeout
  if (parseTimeout !== null) {
    clearTimeout(parseTimeout)
  }

  // Set new timeout for 1 second
  parseTimeout = window.setTimeout(() => {
    const semiformalCode = getEditorContent(specEditor)
    parseCode(semiformalCode)
  }, 1000)
}

/**
 * Initialize application
 */
async function init() {
  console.log('Initializing Semiformal Programming Playground...')

  // Check backend health
  try {
    const health = await api.health()
    console.log('Backend health:', health)
    hasLLM = health.has_openai
    setLLMStatus(health.has_openai)

    if (!health.has_openai) {
      setStatusMessage('Warning: OpenAI API key not configured. LLM features disabled.', 'error')
    }
  } catch (error) {
    console.error('Backend not reachable:', error)
    setStatusMessage('Error: Backend not reachable. Make sure the server is running.', 'error')
    setLLMStatus(false)
  }

  // Create spec editor
  const specContainer = document.getElementById('spec-editor')
  if (!specContainer) {
    console.error('Spec editor container not found')
    return
  }

  specEditor = createEditor(
    specContainer,
    EXAMPLE_SPEC,
    [
      nodeDecorationsField,
      nodesStateField,
      cursorMappingStateField,
      mappingsStateField,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          handleSpecChange()
        }
        if (update.selectionSet) {
          handleCursorMove(update.view)
        }
      })
    ],
    false
  )

  // Create code editor
  const codeContainer = document.getElementById('code-editor')
  if (!codeContainer) {
    console.error('Code editor container not found')
    return
  }

  codeEditor = createEditor(
    codeContainer,
    '# Press Cmd+S in the left editor to generate Python code',
    [
      pythonLineStateField,
      pythonLineDecorationsField
    ],
    false
  )

  // Add Cmd+S / Ctrl+S handler
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      generateCode()
    }
  })

  console.log('Initialization complete!')
  setStatusMessage('Ready. Type to parse (auto-debounced) • Cmd+S to generate', 'success')

  // Initial parse
  parseCode(EXAMPLE_SPEC)
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init)
} else {
  init()
}
