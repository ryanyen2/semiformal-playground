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
import { createEditor, getEditorContent, detectChanges, type ChangeInfo } from './editor'
import {
  nodeDecorationsField,
  nodesStateField,
  cursorMappingStateField,
  pythonLineStateField,
  pythonLineDecorationsField,
  updateNodeDecorations,
  updateCursorMapping,
  updatePythonLineHighlight,
  findNodeAtCursor,
  findMappingForNode
} from './decorations'
import { api, IntentNode, NodeMapping } from './api'
import { ASTViewer } from './ast-viewer'

// Initial example code
const EXAMPLE_SPEC = `result = load the dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)
`

// Application state
let specEditor: EditorView
let codeEditor: EditorView
let astViewer: ASTViewer
let parseTimeout: number | null = null
let isGenerating = false
let isParsing = false

// Current state
let currentNodes: IntentNode[] = []
let currentMappings: NodeMapping[] = []
let lastSpecCode = ''
let lastPythonCode = ''
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
 * Apply a semiformal edit through the unified /edit/semiformal endpoint.
 * The backend decides whether this is an initial generation or a refinement.
 */
async function applySemiformalEdit(oldCode: string, newCode: string) {
  if (isParsing) return
  isParsing = true

  try {
    setSpecStatus('Parsing...', 'parsing')
    setStatusMessage('Parsing semiformal code...', 'parsing')

    const newLines = newCode.split('\n')
    const oldLines = oldCode.split('\n')

    // Compute a minimal change description to send to the backend.
    let change: ChangeInfo | null = null
    if (oldCode && oldCode !== newCode) {
      change = detectChanges(oldCode, newCode)
    }

    const hasPrevious = !!oldCode
    const fromLine = change ? change.fromLine : 0
    const newLineText = newLines[fromLine] ?? ''
    const oldLineText = hasPrevious ? oldLines[fromLine] ?? '' : undefined

    const editResult = await api.editSemiformal(
      String(fromLine),
      newLineText,
      newCode,
      oldLineText,
      fromLine,
      {
        from_side: 'semiformal'
      }
    )

    // Update Python code editor with generated/refined code
    codeEditor.dispatch({
      changes: {
        from: 0,
        to: codeEditor.state.doc.length,
        insert: editResult.python_code
      }
    })

    lastSpecCode = newCode
    lastPythonCode = editResult.python_code

    // Refresh nodes and mappings from backend state so mapping/AST stay in sync
    const state = await api.getState()
    currentNodes = state.nodes
    currentMappings = state.mappings

    // Update decorations
    updateNodeDecorations(specEditor, currentNodes)

    // Update AST viewer
    astViewer.updateTree(currentNodes, currentMappings)

    // Update UI
    setNodeCount(currentNodes.length)
    setSpecStatus('Parsed', '')
    setCodeStatus('Generated', '')
    setStatusMessage(editResult.message, 'success')

    console.log('Semiformal edit result:', editResult)
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
 * Parse semiformal code (debounced) using the unified edit pipeline.
 */
async function parseCode(semiformalCode: string) {
  await applySemiformalEdit(lastSpecCode, semiformalCode)
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

    await applySemiformalEdit(lastSpecCode, semiformalCode)

    setCodeStatus('Generated', '')
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
 * Calculate the length of the token to highlight based on node and mapping
 */
function calculateTokenLength(node: IntentNode, mapping: NodeMapping): number {
  // For identifiers and function calls, use the node value length
  if (node.type === 'identifier' || node.type === 'function_call') {
    return node.value.length
  }

  // For operators, use the node value length
  if (node.type === 'operator') {
    return node.value.length
  }

  // For literals, try to find the actual representation in the snippet
  if (node.type === 'literal') {
    // The snippet might have quotes around strings, so try to find the actual token
    const snippet = mapping.code_snippet
    const col = mapping.code_col
    
    // Extract the token starting at the column position
    if (snippet && col >= 0) {
      // Get the line from the snippet (in case it's multi-line)
      const lines = snippet.split('\n')
      if (lines.length > 0) {
        const firstLine = lines[0]
        // Try to extract a token starting at col
        const remaining = firstLine.substring(col)
        const tokenMatch = remaining.match(/^(\w+|'[^']*'|"[^"]*"|\d+\.?\d*|[^\s\w]+)/)
        if (tokenMatch) {
          return tokenMatch[1].length
        }
      }
    }
    return node.value.length
  }

  // For NL phrases and holes, highlight a reasonable portion of the generated code
  // Use the snippet to determine length
  const snippet = mapping.code_snippet
  if (snippet) {
    // For single-line snippets, use the whole snippet length
    const lines = snippet.split('\n')
    if (lines.length === 1) {
      return Math.min(snippet.length, 80) // Cap at 80 chars for readability
    }
    // For multi-line, highlight the first line
    return Math.min(lines[0].length - mapping.code_col, 80)
  }

  // Default fallback
  return Math.max(node.value.length, 5)
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
      const node = currentNodes[nodeIndex]
      console.log(`Cursor on node #${nodeIndex}:`, node)
      console.log(`Maps to Python line ${mapping.code_line}, col ${mapping.code_col}:`, mapping.code_snippet)

      // Calculate token length from node value or snippet
      // Try to extract the actual token from the snippet
      const tokenLength = calculateTokenLength(node, mapping)

      // Highlight the Python token in the code editor
      updatePythonLineHighlight(codeEditor, {
        line: mapping.code_line,
        col: mapping.code_col,
        length: tokenLength
      })
    } else {
      // Clear Python line highlight if no mapping
      updatePythonLineHighlight(codeEditor, null)
    }

    // Expand AST viewer to show this node
    astViewer.expandToNode(nodeIndex)
  } else {
    // Clear Python line highlight if no node
    updatePythonLineHighlight(codeEditor, null)
    astViewer.clearSelection()
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

  // Create AST viewer
  const astViewerContainer = document.getElementById('ast-viewer')
  if (!astViewerContainer) {
    console.error('AST viewer container not found')
    return
  }

  astViewer = new ASTViewer(astViewerContainer)

  // Set up AST viewer callbacks
  astViewer.setCallbacks({
    onNodeClick: (nodeIndex) => {
      // When clicking a node in the tree, highlight it in both editors
      const node = currentNodes[nodeIndex]
      const mapping = findMappingForNode(currentMappings, nodeIndex)

      // Highlight in spec editor
      updateCursorMapping(specEditor, nodeIndex)

      // Highlight in Python editor
      if (mapping) {
        const tokenLength = calculateTokenLength(node, mapping)
        updatePythonLineHighlight(codeEditor, {
          line: mapping.code_line,
          col: mapping.code_col,
          length: tokenLength
        })
      }
    }
  })

  // Add Cmd+S / Ctrl+S handler
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      generateCode()
    }
  })

  console.log('Initialization complete!')
  setStatusMessage('Ready. Type to parse (auto-debounced) • Cmd+S to generate', 'success')

  // Initial parse (treated as first edit with no previous code)
  lastSpecCode = ''
  lastPythonCode = ''
  parseCode(EXAMPLE_SPEC)
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init)
} else {
  init()
}
