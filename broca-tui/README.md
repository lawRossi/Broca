# Broca TUI

Terminal User Interface for the Broca Agent Framework, built with [Textual](https://textual.textualize.io/).

## Features

- **Session Management**: Create, list, and manage chat sessions
- **Chat Interface**: Three-panel layout with agent sidebar, message list, and info sidebar
- **Crew Execution**: Submit and monitor orchestration executions
- **Real-time Updates**: Socket.IO integration for live message streaming

## Installation

```bash
# From the broca-tui directory
pip install -e .

# Or as part of main broca installation
cd /path/to/broca && pip install -e broca-tui/
```

## Usage

```bash
# Start the TUI
broca-tui

# Or via broca CLI
broca tui

# Open a specific session directly
broca tui --session <session_id>
```

## Configuration

Configuration is loaded from:
1. Environment variables (`BROCA_SOCKET_SERVER_URL`, `BROCA_API_SERVER_URL`)
2. `~/.broca/configs/configs.json`

## Key Bindings

| Key | Action |
|-----|--------|
| `Ctrl+C` | Exit application |
| `Ctrl+S` | Return to session list |
| `?` | Show help |
| `Ctrl+N` | New session |
| `Ctrl+F` | Search sessions |
| `Ctrl+L` | Toggle left sidebar |
| `Ctrl+R` | Toggle right sidebar |
| `Ctrl+E` | Jump to crew management |

## Architecture

```
broca-tui/
├── broca_tui/
│   ├── app.py           # Main Textual App
│   ├── config.py        # Configuration
│   ├── screens/         # Screen implementations
│   │   ├── session_list.py
│   │   ├── chat.py
│   │   └── crew_executions.py
│   ├── widgets/         # Reusable widgets
│   │   ├── chat_header.py
│   │   ├── agent_sidebar.py
│   │   ├── message_list.py
│   │   ├── message_item.py
│   │   ├── chat_input.py
│   │   ├── info_sidebar.py
│   │   ├── permission_dialog.py
│   │   ├── agent_query_dialog.py
│   │   └── session_card.py
│   ├── stores/          # State management
│   │   ├── session_store.py
│   │   ├── chat_store.py
│   │   ├── agent_store.py
│   │   └── crew_store.py
│   └── api/             # REST API clients
│       ├── client.py
│       ├── session.py
│       └── crew.py
├── theme/               # TCSS theme files
│   ├── theme.tcss
│   └── app.tcss
├── pyproject.toml
└── README.md
```
