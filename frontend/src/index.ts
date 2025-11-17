/**
 * Main entry point for IR-based bidirectional programming.
 *
 * Workflow:
 * - Auto-parse with debounce as user edits spec
 * - Cmd/Ctrl+S triggers LLM code generation
 * - Tree viewer shows IR structure with mappings
 * - CodeMirror decorations highlight mapped nodes
 */

import { EditorView, keymap } from '@codemirror/view'
import { createEditor, getEditorContent, setEditorContent } from './editor'
import { parse, generate, skeleton, getMappings, IRNode, ASTMapping, ProgramIR } from './api'
import { ASTViewer } from './ast-viewer'

// Example code
const EXAMPLE_SPEC = `def process_data(filename):
    data = load the CSV file from filename
    cleaned = remove missing values from data
    return cleaned

result = process_data("data.csv")
print(result)
`

// Application state
let specEditor: EditorView
let codeEditor: EditorView
let astViewer: ASTViewer

let currentIR: ProgramIR | null = null
let currentMappings: Record<string, ASTMapping> = {}
let isGenerating = false
let parseTimeout: number | null = null

const PARSE_DEBOUNCE_MS = 1000

/**
 * UI status helpers
 */
function setStatus(message: string, type: 'info' | 'error' | 'success' | 'generating' = 'info') {
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

/**
 * Parse semiformal code (debounced)
 */
async function parseCode() {
  try {
    const semiformalCode = getEditorContent(specEditor)

    setStatus('Parsing...', 'info')

    const result = await parse(semiformalCode)

    currentIR = result.ir

    // Update code editor with skeleton
    setEditorContent(codeEditor, result.skeleton_code)

    // Update AST viewer
    astViewer.updateNodes(Object.values(result.ir.nodes))

    // Update status
    const incompleteCount = result.incomplete_nodes.length
    setNodeCount(Object.keys(result.ir.nodes).length)

    if (incompleteCount > 0) {
      setStatus(`Parsed (${incompleteCount} incomplete)`, 'info')
    } else {
      setStatus('Parsed (complete)', 'success')
    }

    console.log('Parse result:', result)
  } catch (error) {
    console.error('Parse error:', error)
    setStatus(`Parse error: ${error instanceof Error ? error.message : String(error)}`, 'error')
  }
}

/**
 * Debounced parse
 */
function debouncedParse() {
  if (parseTimeout !== null) {
    clearTimeout(parseTimeout)
  }
  parseTimeout = window.setTimeout(parseCode, PARSE_DEBOUNCE_MS)
}

/**
 * Generate Python code with LLM (Cmd+S)
 */
async function generateCode() {
  if (isGenerating) return
  isGenerating = true

  try {
    const semiformalCode = getEditorContent(specEditor)

    setStatus('Generating code with LLM...', 'generating')

    const result = await generate(semiformalCode)

    currentIR = result.ir
    currentMappings = result.mappings

    // Update code editor
    setEditorContent(codeEditor, result.generated_code)

    // Update AST viewer with mappings
    astViewer.updateNodes(Object.values(result.ir.nodes))

    // Update status
    setStatus('Code generated successfully', 'success')
    setNodeCount(Object.keys(result.ir.nodes).length)

    console.log('Generation result:', result)
    console.log('Mappings:', result.mappings)
  } catch (error) {
    console.error('Generation error:', error)
    setStatus(`Generation error: ${error instanceof Error ? error.message : String(error)}`, 'error')
  } finally {
    isGenerating = false
  }
}

/**
 * Update mappings after code changes
 */
async function updateMappings() {
  try {
    const semiformalCode = getEditorContent(specEditor)
    const generatedCode = getEditorContent(codeEditor)

    if (!semiformalCode || !generatedCode) return

    const result = await getMappings(semiformalCode, generatedCode)

    currentIR = result.ir
    currentMappings = result.mappings

    console.log('Updated mappings:', result.mappings)
  } catch (error) {
    console.error('Mapping error:', error)
  }
}

/**
 * Initialize application
 */
async function init() {
  // Create spec editor (left)
  const specContainer = document.getElementById('spec-editor')
  if (!specContainer) throw new Error('Spec editor container not found')

  specEditor = createEditor(
    specContainer,
    EXAMPLE_SPEC,
    [
      keymap.of([
        {
          key: 'Mod-s',
          preventDefault: true,
          run: () => {
            generateCode()
            return true
          },
        },
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          debouncedParse()
        }
      }),
    ]
  )

  // Create code editor (right)
  const codeContainer = document.getElementById('code-editor')
  if (!codeContainer) throw new Error('Code editor container not found')

  codeEditor = createEditor(
    codeContainer,
    '',
    [
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          // Update mappings when code changes
          setTimeout(updateMappings, 500)
        }
      }),
    ]
  )

  // Create AST viewer
  const astContainer = document.getElementById('ast-viewer')
  if (!astContainer) throw new Error('AST viewer container not found')

  astViewer = new ASTViewer(astContainer)

  // Initial parse
  await parseCode()

  setStatus('Ready - Press Cmd/Ctrl+S to generate code', 'success')
}

// Start application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init)
} else {
  init()
}
