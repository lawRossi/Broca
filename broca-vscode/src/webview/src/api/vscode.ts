// VSCode WebView API wrapper

interface VSCodeAPI {
  postMessage(message: any): void
  getState(): any
  setState(state: any): void
}

// The acquireVsCodeApi function is injected by VSCode at runtime
declare function acquireVsCodeApi(): VSCodeAPI

let vscodeApi: VSCodeAPI | null = null

export function getVSCodeAPI(): VSCodeAPI {
  if (!vscodeApi) {
    try {
      vscodeApi = acquireVsCodeApi()
    } catch {
      // Fallback for development outside VSCode
      vscodeApi = {
        postMessage: (msg: any) => {
          console.log('[VSCode API] postMessage:', msg)
        },
        getState: () => null,
        setState: () => {},
      }
    }
  }
  return vscodeApi
}

export function postMessage(message: any): void {
  getVSCodeAPI().postMessage(message)
}

export function onMessage(handler: (message: any) => void): () => void {
  const listener = (event: MessageEvent) => {
    handler(event.data)
  }
  window.addEventListener('message', listener)
  return () => window.removeEventListener('message', listener)
}

export interface InitialData {
  sessionId: string
  token: string
  supabaseUrl: string
  supabaseKey: string
  vscode: VSCodeAPI
}

export function getInitialData(): InitialData {
  return (window as any).__INITIAL_DATA__
}
