/**
 * Synchronization logic for bidirectional programming.
 */

import { api } from './api'
import type { ChangeInfo } from './editor'

export interface SyncState {
  specCode: string
  generatedCode: string
  isGenerating: boolean
  lastParseResult: any
}

/**
 * Analyze changes and determine sync action.
 */
export interface SyncAction {
  type: 'add_param' | 'rename_func' | 'insert_statement' | 'edit_line' | 'none'
  location: string
  content: string
  line?: number
}

export function analyzeSpecChange(
  oldCode: string,
  newCode: string,
  change: ChangeInfo
): SyncAction {
  const oldLines = oldCode.split('\n')
  const newLines = newCode.split('\n')

  const changedLine = newLines[change.fromLine]
  if (!changedLine) {
    return { type: 'none', location: '', content: '' }
  }

  // Check for parameter addition
  // Example: def foo() -> def foo(x)
  const oldDef = oldLines[change.fromLine]
  if (oldDef && changedLine.includes('def ') && oldDef.includes('def ')) {
    const funcNameMatch = changedLine.match(/def\s+(\w+)/)
    const oldFuncNameMatch = oldDef.match(/def\s+(\w+)/)

    if (funcNameMatch && oldFuncNameMatch) {
      const funcName = funcNameMatch[1]
      const oldFuncName = oldFuncNameMatch[1]

      // Check for rename
      if (funcName !== oldFuncName) {
        return {
          type: 'rename_func',
          location: oldFuncName,
          content: funcName
        }
      }

      // Check for parameter addition
      const newParams = extractParams(changedLine)
      const oldParams = extractParams(oldDef)

      if (newParams.length > oldParams.length) {
        const addedParam = newParams[newParams.length - 1]
        return {
          type: 'add_param',
          location: funcName,
          content: addedParam
        }
      }
    }
  }

  // Check for statement insertion inside a function
  // Look for new lines added within a function body
  if (change.insertedText && !change.insertedText.startsWith('def ')) {
    // Find which function this line belongs to
    const funcName = findContainingFunction(newLines, change.fromLine)
    if (funcName) {
      return {
        type: 'insert_statement',
        location: funcName,
        content: change.insertedText.trim()
      }
    }
  }

  return { type: 'none', location: '', content: '' }
}

export function analyzeCodeChange(
  oldCode: string,
  newCode: string,
  change: ChangeInfo
): SyncAction {
  const newLines = newCode.split('\n')
  const changedLine = newLines[change.fromLine]

  if (!changedLine) {
    return { type: 'none', location: '', content: '' }
  }

  // Find which function this edit belongs to
  const funcName = findContainingFunction(newLines, change.fromLine)

  if (funcName) {
    return {
      type: 'edit_line',
      location: funcName,
      content: changedLine.trim(),
      line: change.fromLine + 1 // Convert to 1-based
    }
  }

  return { type: 'none', location: '', content: '' }
}

/**
 * Extract parameter names from a function definition line.
 */
function extractParams(line: string): string[] {
  const match = line.match(/def\s+\w+\((.*?)\)/)
  if (!match) return []

  const paramsStr = match[1].trim()
  if (!paramsStr) return []

  return paramsStr.split(',').map(p => p.trim().split('=')[0].trim())
}

/**
 * Find the name of the function containing a given line.
 */
function findContainingFunction(lines: string[], lineIndex: number): string | null {
  // Search backwards for the nearest function definition
  for (let i = lineIndex; i >= 0; i--) {
    const line = lines[i]
    const match = line.match(/^def\s+(\w+)\(/)
    if (match) {
      return match[1]
    }
    // Stop if we hit a non-indented line that's not a function
    if (line.length > 0 && !line.startsWith(' ') && !line.startsWith('\t') && !match) {
      break
    }
  }
  return null
}

/**
 * Synchronization manager.
 */
export class SyncManager {
  private state: SyncState = {
    specCode: '',
    generatedCode: '',
    isGenerating: false,
    lastParseResult: null
  }

  getState(): SyncState {
    return { ...this.state }
  }

  updateSpecCode(code: string) {
    this.state.specCode = code
  }

  updateGeneratedCode(code: string) {
    this.state.generatedCode = code
  }

  async syncSpecToCode(action: SyncAction): Promise<string> {
    if (action.type === 'none') {
      return this.state.generatedCode
    }

    const result = await api.sync(
      'spec_to_code',
      action.type,
      action.location,
      action.content,
      this.state.specCode,
      this.state.generatedCode,
      action.line
    )

    this.state.generatedCode = result.updated_code

    // Handle regeneration if needed
    if (result.needs_regeneration) {
      for (const funcName of result.regeneration_targets) {
        const regenerated = await api.regenerate(
          funcName,
          result.updated_code,
          action.content,
          action.type
        )
        this.state.generatedCode = regenerated.updated_code
      }
    }

    return this.state.generatedCode
  }

  async syncCodeToSpec(action: SyncAction): Promise<string> {
    if (action.type === 'none') {
      return this.state.specCode
    }

    const result = await api.sync(
      'code_to_spec',
      action.type,
      action.location,
      action.content,
      this.state.specCode,
      this.state.generatedCode,
      action.line
    )

    this.state.specCode = result.updated_code
    return this.state.specCode
  }

  async generateFromSpec(): Promise<{ code: string; message: string }> {
    this.state.isGenerating = true

    try {
      const result = await api.generate(this.state.specCode)
      this.state.generatedCode = result.generated_code

      return {
        code: result.generated_code,
        message: `Generated code with ${result.incomplete_parts.length} completions`
      }
    } finally {
      this.state.isGenerating = false
    }
  }

  async parseSpec(): Promise<any> {
    const result = await api.parse(this.state.specCode)
    this.state.lastParseResult = result
    return result
  }

  getLastParseResult() {
    return this.state.lastParseResult
  }
}
