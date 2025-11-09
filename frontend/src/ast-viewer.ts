/**
 * AST/IR Tree Viewer Component
 *
 * Interactive tree visualization for parsed intent nodes, inspired by astexplorer.
 *
 * Features:
 * - Expandable/collapsible tree nodes with +/- indicators
 * - Click on node → highlight corresponding tokens in spec/python
 * - Hover on node → highlight corresponding tokens
 * - Auto-expand to show cursor position
 * - Color-coded node types and attributes
 * - Compact, clean display
 */

import type { IntentNode, NodeMapping } from './api'

interface TreeNodeState {
  expanded: boolean
  highlighted: boolean
}

export class ASTViewer {
  private container: HTMLElement
  private nodes: IntentNode[] = []
  private mappings: NodeMapping[] = []
  private nodeStates: Map<number, TreeNodeState> = new Map()
  private selectedNodeIndex: number | null = null

  // Callbacks for interactions
  private onNodeClick?: (nodeIndex: number) => void
  private onNodeHover?: (nodeIndex: number | null) => void

  constructor(container: HTMLElement) {
    this.container = container
    this.render()
  }

  /**
   * Update the tree with new nodes and mappings
   */
  updateTree(nodes: IntentNode[], mappings: NodeMapping[]) {
    this.nodes = nodes
    this.mappings = mappings

    // Initialize node states if needed
    for (let i = 0; i < nodes.length; i++) {
      if (!this.nodeStates.has(i)) {
        this.nodeStates.set(i, { expanded: false, highlighted: false })
      }
    }

    this.render()
  }

  /**
   * Expand tree to show a specific node (for cursor tracking)
   */
  expandToNode(nodeIndex: number) {
    if (nodeIndex < 0 || nodeIndex >= this.nodes.length) return

    // Expand the node and highlight it
    const state = this.nodeStates.get(nodeIndex)
    if (state) {
      state.expanded = true
    }

    this.selectedNodeIndex = nodeIndex
    this.render()

    // Scroll to the node
    this.scrollToNode(nodeIndex)
  }

  /**
   * Clear selection
   */
  clearSelection() {
    this.selectedNodeIndex = null
    this.render()
  }

  /**
   * Set callbacks for interactions
   */
  setCallbacks(callbacks: {
    onNodeClick?: (nodeIndex: number) => void
    onNodeHover?: (nodeIndex: number | null) => void
  }) {
    this.onNodeClick = callbacks.onNodeClick
    this.onNodeHover = callbacks.onNodeHover
  }

  /**
   * Render the tree
   */
  private render() {
    this.container.innerHTML = ''

    if (this.nodes.length === 0) {
      this.container.innerHTML = '<div class="ast-empty">No nodes parsed yet</div>'
      return
    }

    const tree = document.createElement('div')
    tree.className = 'ast-tree'

    // Group nodes by line for hierarchical display
    const nodesByLine = this.groupNodesByLine()

    for (const [lineNum, lineNodes] of nodesByLine) {
      const lineGroup = this.createLineGroup(lineNum, lineNodes)
      tree.appendChild(lineGroup)
    }

    this.container.appendChild(tree)
  }

  /**
   * Group nodes by line number
   */
  private groupNodesByLine(): Map<number, number[]> {
    const grouped = new Map<number, number[]>()

    for (let i = 0; i < this.nodes.length; i++) {
      const node = this.nodes[i]
      const line = node.line

      if (!grouped.has(line)) {
        grouped.set(line, [])
      }
      grouped.get(line)!.push(i)
    }

    return grouped
  }

  /**
   * Create a line group (collapsible)
   */
  private createLineGroup(lineNum: number, nodeIndices: number[]): HTMLElement {
    const group = document.createElement('div')
    group.className = 'ast-line-group'

    // Check if any node in this line is selected
    const hasSelection = nodeIndices.some(idx => idx === this.selectedNodeIndex)
    const groupState = this.nodeStates.get(nodeIndices[0]) || { expanded: false, highlighted: false }
    const isExpanded = groupState.expanded || hasSelection

    // Line header
    const header = document.createElement('div')
    header.className = 'ast-line-header'

    const toggle = document.createElement('span')
    toggle.className = 'ast-toggle'
    toggle.textContent = isExpanded ? '−' : '+'
    toggle.onclick = () => {
      groupState.expanded = !groupState.expanded
      this.render()
    }

    const lineLabel = document.createElement('span')
    lineLabel.className = 'ast-line-label'
    lineLabel.textContent = `Line ${lineNum}`

    const nodeCount = document.createElement('span')
    nodeCount.className = 'ast-node-count'
    nodeCount.textContent = `${nodeIndices.length} node${nodeIndices.length !== 1 ? 's' : ''}`

    header.appendChild(toggle)
    header.appendChild(lineLabel)
    header.appendChild(nodeCount)
    group.appendChild(header)

    // Line nodes (only show if expanded)
    if (isExpanded) {
      const nodesContainer = document.createElement('div')
      nodesContainer.className = 'ast-nodes-container'

      for (const nodeIndex of nodeIndices) {
        const nodeEl = this.createNodeElement(nodeIndex)
        nodesContainer.appendChild(nodeEl)
      }

      group.appendChild(nodesContainer)
    }

    return group
  }

  /**
   * Create a tree node element
   */
  private createNodeElement(nodeIndex: number): HTMLElement {
    const node = this.nodes[nodeIndex]
    const state = this.nodeStates.get(nodeIndex) || { expanded: false, highlighted: false }
    const isSelected = nodeIndex === this.selectedNodeIndex

    const nodeEl = document.createElement('div')
    nodeEl.className = `ast-node ${isSelected ? 'ast-node-selected' : ''}`
    nodeEl.dataset.nodeIndex = String(nodeIndex)

    // Node header with type and value
    const header = document.createElement('div')
    header.className = 'ast-node-header'

    const typeSpan = document.createElement('span')
    typeSpan.className = `ast-node-type ast-type-${node.type}`
    typeSpan.textContent = node.type

    const valueSpan = document.createElement('span')
    valueSpan.className = 'ast-node-value'
    valueSpan.textContent = this.truncate(node.value, 30)

    header.appendChild(typeSpan)
    header.appendChild(document.createTextNode(': '))
    header.appendChild(valueSpan)

    // Position info
    const posSpan = document.createElement('span')
    posSpan.className = 'ast-node-pos'
    posSpan.textContent = `${node.line}:${node.col}`
    header.appendChild(posSpan)

    // Expand toggle for metadata
    const hasMetadata = node.metadata && Object.keys(node.metadata).length > 0
    if (hasMetadata) {
      const metaToggle = document.createElement('span')
      metaToggle.className = 'ast-toggle-small'
      metaToggle.textContent = state.expanded ? '−' : '+'
      metaToggle.onclick = (e) => {
        e.stopPropagation()
        state.expanded = !state.expanded
        this.render()
      }
      header.insertBefore(metaToggle, header.firstChild)
    }

    nodeEl.appendChild(header)

    // Metadata (only show if expanded)
    if (state.expanded && hasMetadata) {
      const metadata = this.createMetadataElement(node.metadata!)
      nodeEl.appendChild(metadata)
    }

    // Click handler
    nodeEl.onclick = (e) => {
      e.stopPropagation()
      this.selectedNodeIndex = nodeIndex
      this.render()

      if (this.onNodeClick) {
        this.onNodeClick(nodeIndex)
      }
    }

    // Hover handlers
    nodeEl.onmouseenter = () => {
      if (this.onNodeHover) {
        this.onNodeHover(nodeIndex)
      }
    }

    nodeEl.onmouseleave = () => {
      if (this.onNodeHover) {
        this.onNodeHover(null)
      }
    }

    return nodeEl
  }

  /**
   * Create metadata display
   */
  private createMetadataElement(metadata: Record<string, any>): HTMLElement {
    const metaEl = document.createElement('div')
    metaEl.className = 'ast-metadata'

    for (const [key, value] of Object.entries(metadata)) {
      const item = document.createElement('div')
      item.className = 'ast-metadata-item'

      const keySpan = document.createElement('span')
      keySpan.className = 'ast-metadata-key'
      keySpan.textContent = key

      const valueSpan = document.createElement('span')
      valueSpan.className = 'ast-metadata-value'
      valueSpan.textContent = this.formatValue(value)

      item.appendChild(keySpan)
      item.appendChild(document.createTextNode(': '))
      item.appendChild(valueSpan)
      metaEl.appendChild(item)
    }

    return metaEl
  }

  /**
   * Format metadata value
   */
  private formatValue(value: any): string {
    if (typeof value === 'boolean') {
      return value ? 'true' : 'false'
    }
    if (typeof value === 'object') {
      return JSON.stringify(value)
    }
    return String(value)
  }

  /**
   * Truncate string
   */
  private truncate(str: string, maxLen: number): string {
    if (str.length <= maxLen) return str
    return str.substring(0, maxLen - 3) + '...'
  }

  /**
   * Scroll to a specific node
   */
  private scrollToNode(nodeIndex: number) {
    setTimeout(() => {
      const nodeEl = this.container.querySelector(`[data-node-index="${nodeIndex}"]`)
      if (nodeEl) {
        nodeEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 100)
  }
}
