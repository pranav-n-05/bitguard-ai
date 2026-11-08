import { Component, type ReactNode } from 'react'
import { Button } from './ui/primitives'

interface State { error: Error | null }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }
  static getDerivedStateFromError(error: Error): State {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="m-6 rounded-md border border-crit/40 bg-crit/10 p-4 text-sm">
          <p className="font-medium text-crit">This view failed to render.</p>
          <p className="mt-1 text-muted">{this.state.error.message}</p>
          <Button size="sm" className="mt-3" onClick={() => this.setState({ error: null })}>Try again</Button>
        </div>
      )
    }
    return this.props.children
  }
}
