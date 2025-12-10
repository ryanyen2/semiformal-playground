/**
 * CodeMirror editor setup and configuration.
 */

import { EditorView, basicSetup, lineNumbers } from 'codemirror'
import { python } from '@codemirror/lang-python'
import { EditorState, Extension } from '@codemirror/state'
import { keymap } from '@codemirror/view'
import { defaultKeymap, indentWithTab } from '@codemirror/commands'
import { indentOnInput } from '@codemirror/language'
import { basicLight } from '@fsegurai/codemirror-theme-basic-light'
import { semiformalHighlighting } from './semiformal-lang'

/**
 * Create a CodeMirror editor instance.
 */
export function createEditor(
  parent: HTMLElement,
  initialDoc: string = '',
  extensions: Extension[] = [],
  readOnly: boolean = false,
  enableSemiformalHighlighting: boolean = false
): EditorView {
  const baseExtensions: Extension[] = [
    basicSetup,
    python(),
    basicLight,
    indentOnInput(),
    keymap.of([
      ...defaultKeymap,
      indentWithTab  // Enable Tab for indentation
    ]),
    EditorView.editable.of(!readOnly),
    EditorView.theme({
      '&': {
        height: '100%'
      },
      '.cm-content': {
        fontFamily: '"Fira Code", "Consolas", "Monaco", monospace',
        fontSize: '14px'
      }
    }),
    ...extensions
  ]
  
  // Add semiformal syntax highlighting only if requested
  if (enableSemiformalHighlighting) {
    baseExtensions.push(semiformalHighlighting())
  }
  
  const state = EditorState.create({
    doc: initialDoc,
    extensions: baseExtensions
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
