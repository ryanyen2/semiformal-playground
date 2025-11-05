/**
 * CodeMirror editor setup and configuration.
 */

import { EditorView, basicSetup } from 'codemirror'
import { python } from '@codemirror/lang-python'
import { EditorState, Extension } from '@codemirror/state'
import { keymap } from '@codemirror/view'
import { defaultKeymap } from '@codemirror/commands'

/**
 * Create a CodeMirror editor instance.
 */
export function createEditor(
  parent: HTMLElement,
  initialDoc: string = '',
  extensions: Extension[] = [],
  readOnly: boolean = false
): EditorView {
  const state = EditorState.create({
    doc: initialDoc,
    extensions: [
      basicSetup,
      python(),
      keymap.of(defaultKeymap),
      EditorView.editable.of(!readOnly),
      EditorView.theme({
        '&': {
          height: '100%',
          backgroundColor: '#1e1e1e'
        },
        '.cm-content': {
          fontFamily: '"Fira Code", "Consolas", "Monaco", monospace',
          fontSize: '14px',
          caretColor: '#528bff'
        },
        '.cm-gutters': {
          backgroundColor: '#1e1e1e',
          color: '#858585',
          border: 'none'
        },
        '.cm-activeLineGutter': {
          backgroundColor: '#2a2a2a'
        },
        '.cm-line': {
          color: '#d4d4d4'
        },
        '&.cm-focused .cm-cursor': {
          borderLeftColor: '#528bff'
        },
        '&.cm-focused .cm-selectionBackground, ::selection': {
          backgroundColor: '#264f78'
        },
        '.cm-activeLine': {
          backgroundColor: '#2a2a2a'
        }
      }),
      ...extensions
    ]
  })

  return new EditorView({
    state,
    parent
  })
}

/**
 * Get the current document content from an editor.
 */
export function getEditorContent(editor: EditorView): string {
  return editor.state.doc.toString()
}

/**
 * Set the content of an editor.
 */
export function setEditorContent(editor: EditorView, content: string) {
  editor.dispatch({
    changes: {
      from: 0,
      to: editor.state.doc.length,
      insert: content
    }
  })
}

/**
 * Insert text at the cursor position.
 */
export function insertAtCursor(editor: EditorView, text: string) {
  const selection = editor.state.selection.main
  editor.dispatch({
    changes: {
      from: selection.from,
      to: selection.to,
      insert: text
    },
    selection: { anchor: selection.from + text.length }
  })
}

/**
 * Get the line number at the cursor position.
 */
export function getCursorLine(editor: EditorView): number {
  const pos = editor.state.selection.main.head
  return editor.state.doc.lineAt(pos).number
}

/**
 * Get text of a specific line.
 */
export function getLineText(editor: EditorView, lineNum: number): string | null {
  const doc = editor.state.doc
  if (lineNum < 1 || lineNum > doc.lines) {
    return null
  }
  return doc.line(lineNum).text
}

/**
 * Detect changes in the editor and return change info.
 */
export interface ChangeInfo {
  fromLine: number
  toLine: number
  insertedText: string
  deletedText: string
}

export function detectChanges(
  oldContent: string,
  newContent: string
): ChangeInfo | null {
  const oldLines = oldContent.split('\n')
  const newLines = newContent.split('\n')

  // Find first changed line
  let fromLine = 0
  for (let i = 0; i < Math.min(oldLines.length, newLines.length); i++) {
    if (oldLines[i] !== newLines[i]) {
      fromLine = i
      break
    }
  }

  // Find last changed line
  let toLine = oldLines.length - 1
  for (let i = 0; i < Math.min(oldLines.length, newLines.length); i++) {
    const oldIdx = oldLines.length - 1 - i
    const newIdx = newLines.length - 1 - i
    if (oldLines[oldIdx] !== newLines[newIdx]) {
      toLine = oldIdx
      break
    }
  }

  if (fromLine === 0 && toLine === oldLines.length - 1 && oldContent === newContent) {
    return null // No changes
  }

  return {
    fromLine,
    toLine,
    insertedText: newLines.slice(fromLine, fromLine + (newLines.length - oldLines.length) + (toLine - fromLine + 1)).join('\n'),
    deletedText: oldLines.slice(fromLine, toLine + 1).join('\n')
  }
}
