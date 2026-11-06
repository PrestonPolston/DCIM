import { Component, type ReactNode } from 'react'

/** Any render/three.js crash in the 3D chunk falls back to the 2D row front. */
export default class Row3DBoundary extends Component<{ fallback: (err: Error) => ReactNode; children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) { return { err } }
  render() { return this.state.err ? this.props.fallback(this.state.err) : this.props.children }
}
