/**
 * Main entry point for the semiformal programming playground.
 */

import { EditorView } from '@codemirror/view'
import { createEditor, getEditorContent, setEditorContent, detectChanges } from './editor'
import { DecorationManager, createDecorationPlugin } from './decorations'
import { SyncManager, analyzeSpecChange, analyzeCodeChange } from './sync'

// Initial example code
const EXAMPLE_SPEC = `# Semiformal Python Example
# Try writing incomplete code!

# Example 1: Function without declaration
result = process_data(raw_input)

# Example 2: Variable with natural language
x = split dataset into training and test sets

# Example 3: Function call with stub
output = transform(x)

def transform(data):
    ...

print(result, x, output)
`

// Application state
let specEditor: EditorView
let codeEditor: EditorView
let specDecorationManager: DecorationManager
let syncManager: SyncManager

let lastSpecContent = EXAMPLE_SPEC
let lastCodeContent = ''

// Status bar management
function showStatus(message: string, type: 'info' | 'error' | 'success' = 'info') {
  const statusBar = document.getElementById('status-bar')
  if (!statusBar) return

  statusBar.textContent = message
  statusBar.className = `status-bar ${type}`
  statusBar.style.display = 'block'

  if (type !== 'error') {
    setTimeout(() => {
      statusBar.style.display = 'none'
    }, 3000)
  }
}

// Initialize application
function init() {
  console.log('Initializing Semiformal Programming Playground...')

  // Initialize managers
  specDecorationManager = new DecorationManager()
  syncManager = new SyncManager()
  syncManager.updateSpecCode(EXAMPLE_SPEC)

  // Create spec editor
  const specContainer = document.getElementById('spec-editor')
  if (!specContainer) {
    console.error('Spec editor container not found')
    return
  }

  specEditor = createEditor(
    specContainer,
    EXAMPLE_SPEC,
    [createDecorationPlugin(specDecorationManager)],
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
    '# Generated code will appear here',
    [],
    false
  )

  // Set up event listeners
  setupEventListeners()

  // Listen for changes in spec editor
  specEditor.dom.addEventListener('blur', handleSpecChange)

  // Listen for changes in code editor
  codeEditor.dom.addEventListener('blur', handleCodeChange)

  console.log('Initialization complete!')
  showStatus('Ready! Try editing the semiformal code and click "Generate Code"', 'success')
}

// Set up button event listeners
function setupEventListeners() {
  const parseBtn = document.getElementById('parseBtn')
  const generateBtn = document.getElementById('generateBtn')
  const syncToSpecBtn = document.getElementById('syncToSpecBtn')

  parseBtn?.addEventListener('click', handleParse)
  generateBtn?.addEventListener('click', handleGenerate)
  syncToSpecBtn?.addEventListener('click', handleSyncToSpec)
}

// Handle parse button click
async function handleParse() {
  try {
    showStatus('Parsing...', 'info')
    const specCode = getEditorContent(specEditor)
    syncManager.updateSpecCode(specCode)

    const result = await syncManager.parseSpec()

    // Update decorations
    specDecorationManager.updateIncompleteParts(result.incomplete_parts)
    specDecorationManager.updateStubs(result.stubs)

    // Show annotated code in the spec editor
    setEditorContent(specEditor, result.annotated_code)
    lastSpecContent = result.annotated_code
    syncManager.updateSpecCode(result.annotated_code)

    showStatus(
      `Parsed: ${result.incomplete_parts.length} incomplete parts, ${result.stubs.length} stubs created`,
      'success'
    )
  } catch (error) {
    console.error('Parse error:', error)
    showStatus(`Parse error: ${error instanceof Error ? error.message : String(error)}`, 'error')
  }
}

// Handle generate button click
async function handleGenerate() {
  try {
    showStatus('Generating code with LLM...', 'info')
    const specCode = getEditorContent(specEditor)
    syncManager.updateSpecCode(specCode)

    const result = await syncManager.generateFromSpec()

    // Update code editor
    setEditorContent(codeEditor, result.code)
    lastCodeContent = result.code

    showStatus(result.message, 'success')
  } catch (error) {
    console.error('Generation error:', error)
    showStatus(
      `Generation error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  }
}

// Handle spec changes (automatic sync to code)
async function handleSpecChange() {
  const currentContent = getEditorContent(specEditor)

  if (currentContent === lastSpecContent) {
    return // No changes
  }

  const change = detectChanges(lastSpecContent, currentContent)
  if (!change) {
    return
  }

  try {
    // Analyze the change
    const action = analyzeSpecChange(lastSpecContent, currentContent, change)

    if (action.type !== 'none') {
      showStatus(`Syncing ${action.type}...`, 'info')

      // Update sync manager state
      syncManager.updateSpecCode(currentContent)
      const currentCodeContent = getEditorContent(codeEditor)
      syncManager.updateGeneratedCode(currentCodeContent)

      // Perform sync
      const updatedCode = await syncManager.syncSpecToCode(action)

      // Update code editor
      setEditorContent(codeEditor, updatedCode)
      lastCodeContent = updatedCode

      showStatus(`Synced ${action.type} to code`, 'success')
    }

    lastSpecContent = currentContent
  } catch (error) {
    console.error('Spec sync error:', error)
    showStatus(
      `Sync error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  }
}

// Handle code changes (manual sync back to spec via button)
async function handleCodeChange() {
  // Just track changes, don't auto-sync
  lastCodeContent = getEditorContent(codeEditor)
}

// Handle sync to spec button click
async function handleSyncToSpec() {
  const currentCodeContent = getEditorContent(codeEditor)
  const currentSpecContent = getEditorContent(specEditor)

  const change = detectChanges(
    syncManager.getState().generatedCode,
    currentCodeContent
  )

  if (!change) {
    showStatus('No changes to sync', 'info')
    return
  }

  try {
    showStatus('Syncing changes to spec...', 'info')

    // Analyze the change
    const action = analyzeCodeChange(
      syncManager.getState().generatedCode,
      currentCodeContent,
      change
    )

    if (action.type !== 'none') {
      // Update sync manager state
      syncManager.updateSpecCode(currentSpecContent)
      syncManager.updateGeneratedCode(currentCodeContent)

      // Perform sync
      const updatedSpec = await syncManager.syncCodeToSpec(action)

      // Update spec editor
      setEditorContent(specEditor, updatedSpec)
      lastSpecContent = updatedSpec

      showStatus('Synced code changes to spec', 'success')
    } else {
      showStatus('No significant changes to sync', 'info')
    }
  } catch (error) {
    console.error('Code sync error:', error)
    showStatus(
      `Sync error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  }
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init)
} else {
  init()
}
