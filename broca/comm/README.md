# Broca Communication Module

This module provides multi-endpoint communication capabilities using Socket.io, supporting browser, command-line, VSCode plugin, and browser plugin clients.

## Features

- **Multi-endpoint Support**: Communicate with agents from browsers, command-line, VSCode plugins, and browser plugins
- **Message Broadcasting**: Broadcast messages to multiple clients
- **Message Subscription**: Subscribe to specific channels for targeted communication
- **1-to-1 Communication**: Direct communication between specific clients
- **Room-based Communication**: Group communication using rooms
- **Agent Integration**: Seamless integration with existing Agent system
- **Automatic Reconnection**: Automatic reconnection on connection loss
- **Error Handling**: Comprehensive error handling and reporting

## Architecture

```
Broca/comm/
├── __init__.py              # Module initialization
├── message_types.py         # Message type definitions and protocol
├── socketio_server.py       # Socket.io server implementation
├── socketio_client.py       # Socket.io client implementation
├── agent_communicator.py    # Agent communicator (integrates with Agent system)
├── example_server.py        # Example server implementation
├── example_client.py        # Example client implementation
└── README.md                # This file
```

## Message Types

### Main Message Types

- `CONNECT`: Connection events
- `DISCONNECT`: Disconnection events
- `PING/PONG`: Heartbeat messages
- `ERROR`: Error messages
- `USER_MESSAGE`: User input messages
- `AGENT_RESPONSE`: Agent response messages
- `AGENT_THINKING`: Agent thinking/reasoning messages
- `AGENT_ERROR`: Agent error messages
- `TASK_START`: Task start notifications
- `TASK_PROGRESS`: Task progress updates
- `TASK_COMPLETE`: Task completion notifications
- `TASK_FAILED`: Task failure notifications
- `TOOL_CALL`: Tool execution requests
- `TOOL_RESULT`: Tool execution results
- `AGENT_REGISTER`: Agent registration
- `AGENT_UNREGISTER`: Agent unregistration
- `AGENT_LIST`: Agent list request
- `SUBSCRIBE`: Subscription requests
- `UNSUBSCRIBE`: Unsubscription requests
- `BROADCAST`: Broadcast messages
- `COMMAND`: Command messages
- `COMMAND_RESULT`: Command result messages

### Message Subtypes

- `USER_INPUT`: User input
- `USER_COMMAND`: User command
- `USER_FILE`: User file
- `AGENT_TEXT`: Agent text response
- `AGENT_REASONING`: Agent reasoning
- `AGENT_ACTION`: Agent action
- `TASK_CREATE`: Task creation
- `TASK_UPDATE`: Task update
- `TASK_DELETE`: Task deletion
- `TOOL_EXECUTE`: Tool execution
- `TOOL_SUCCESS`: Tool success
- `TOOL_FAILURE`: Tool failure
- `ERROR_CONNECTION`: Connection error
- `ERROR_AUTH`: Authentication error
- `ERROR_VALIDATION`: Validation error
- `ERROR_INTERNAL`: Internal error

## Message Structure

```python
Message(
    message_id="unique-id",           # Unique message identifier
    message_type=MessageType.USER_MESSAGE,  # Message type
    timestamp="2026-01-23T10:00:00",  # ISO 8601 timestamp
    sub_type=MessageSubType.USER_INPUT,  # Optional subtype
    status=MessageStatus.OK,          # Optional status code
    sender_id="client_id",            # Optional sender ID
    receiver_id="agent_id",           # Optional receiver ID
    room="room_name",                 # Optional room name
    subscription="subscription_name", # Optional subscription name
    data={"content": "Hello"},        # Message payload
    metadata={"user_id": "123"},      # Optional metadata
    error_code="ERROR_CODE",          # Optional error code
    error_message="Error message"     # Optional error message
)
```

## Usage

### 1. Running the Server

```bash
# Start the Socket.io server
python Broca/comm/example_server.py
```

The server will start on `http://0.0.0.0:8000` by default.

### 2. Running the Client

```bash
# Start a CLI client
python Broca/comm/example_client.py cli

# Start a browser client (use browser client library)
# Start a VSCode plugin client (use VSCode extension)
```

### 3. Using the Agent Communicator

```python
from Broca.agent_socketio import SocketIOAgent
from Broca.agent import AgentConfig
from Broca.llm import LLMClient

# Create agent configuration
config = AgentConfig()
config.role_description = "You are a helpful assistant"
config.llm_config_name = "minimax"
config.verbose = True

# Create LLM client
llm_client = LLMClient()

# Create Socket.io agent
agent = SocketIOAgent(
    config=config,
    llm_client=llm_client,
    server_url="http://localhost:8000",
    client_type="agent",
    user_id="user_123"
)

# Run the agent
agent.run()
```

### 4. Using the Socket.io Client Directly

```python
from Broca.comm.socketio_client import SocketIOClient
from Broca.comm.message_types import MessageProtocol
import asyncio

async def main():
    # Create client
    client = SocketIOClient(
        server_url="http://localhost:8000",
        client_type="cli",
        client_id="my_client",
        user_id="user_123"
    )
    
    # Register event handlers
    @client.on_connect
    async def on_connect():
        print("Connected!")
        await client.subscribe("my_channel")
    
    @client.on_user_message
    async def on_user_message(message):
        print(f"Received: {message.data.get('content')}")
    
    # Connect and send message
    await client.connect()
    await client.send_user_message("Hello from client!")
    
    # Wait for messages
    await asyncio.sleep(10)
    
    # Disconnect
    await client.disconnect()

asyncio.run(main())
```

### 5. Using the Socket.io Server Directly

```python
from Broca.comm.socketio_server import SocketIOServer
from Broca.comm.message_types import MessageProtocol
import asyncio

async def main():
    # Create server
    server = SocketIOServer(
        host="0.0.0.0",
        port=8000,
        cors_allowed_origins="*"
    )
    
    # Register event handlers
    @server.on("connect")
    async def on_connect(client_info):
        print(f"Client connected: {client_info.client_id}")
    
    @server.on("user_message")
    async def on_user_message(client_info, message):
        print(f"User message: {message.data.get('content')}")
        
        # Echo back
        echo_msg = MessageProtocol.create_user_message(
            content=f"Echo: {message.data.get('content')}",
            sender_id="server",
            receiver_id=client_info.client_id
        )
        await server.send_message(echo_msg, client_id=client_info.client_id)
    
    # Start server
    await server.start()

asyncio.run(main())
```

## Communication Patterns

### 1. Broadcasting

```python
# Server broadcasts to all clients
await server.broadcast("Hello everyone!")

# Client broadcasts to all clients
await client.broadcast("Hello from client!")
```

### 2. Subscription-based Communication

```python
# Subscribe to a channel
await client.subscribe("agent_updates")

# Send message to subscribers
await client.send_user_message(
    content="Update message",
    subscription="agent_updates"
)
```

### 3. 1-to-1 Communication

```python
# Send message to specific client
await client.send_user_message(
    content="Hello specific client",
    receiver_id="target_client_id"
)
```

### 4. Room-based Communication

```python
# Join a room
await client.subscribe("room_123")

# Send message to room
await client.send_user_message(
    content="Hello room",
    room="room_123"
)
```

### 5. Command-based Communication

```python
# Send command
await client.send_command(
    command="get_status",
    arguments={"detail": True}
)

# Handle command result
@client.on_command_result
async def on_command_result(message):
    print(f"Command result: {message.data.get('result')}")
```

## Integration with Existing Agent System

The `SocketIOAgent` class extends the existing `Agent` class to support Socket.io communication:

```python
from Broca.agent_socketio import SocketIOAgent
from Broca.agent import AgentConfig
from Broca.llm import LLMClient

# Create agent
config = AgentConfig()
config.role_description = "You are a helpful assistant"
config.llm_config_name = "minimax"

llm_client = LLMClient()

agent = SocketIOAgent(
    config=config,
    llm_client=llm_client,
    server_url="http://localhost:8000",
    client_type="agent"
)

# Run agent (replaces command-line interaction)
agent.run()
```

The agent will:
1. Connect to the Socket.io server
2. Subscribe to agent-specific channels
3. Receive user messages via Socket.io
4. Process messages and send responses
5. Handle tool calls and task execution
6. Support multi-endpoint communication

## Client Types

- **CLI**: Command-line interface client
- **Browser**: Web browser client (using Socket.io JavaScript client)
- **VSCode**: VSCode extension client
- **Browser Plugin**: Browser extension client
- **Agent**: Agent system client

## Error Handling

The module provides comprehensive error handling:

```python
@client.on_error
async def on_error(message):
    print(f"Error: {message.error_message}")
    print(f"Error code: {message.error_code}")
```

Common error codes:
- `VALIDATION_ERROR`: Message validation failed
- `PARSE_ERROR`: JSON parsing failed
- `PROCESS_ERROR`: Message processing failed
- `UNKNOWN_COMMAND`: Unknown command received
- `CLIENT_NOT_FOUND`: Client not found
- `SUBSCRIPTION_ERROR`: Subscription failed

## Configuration

### Server Configuration

```python
server = SocketIOServer(
    host="0.0.0.0",           # Server host
    port=8000,                # Server port
    cors_allowed_origins="*"  # CORS allowed origins
)
```

### Client Configuration

```python
client = SocketIOClient(
    server_url="http://localhost:8000",  # Server URL
    client_type="cli",                   # Client type
    client_id="my_client",               # Client ID
    user_id="user_123",                  # User ID
    auto_reconnect=True,                 # Auto reconnect
    reconnect_delay=1.0,                 # Reconnect delay
    max_reconnect_attempts=5             # Max reconnect attempts
)
```

## Dependencies

```toml
[tool.poetry.dependencies]
python = "^3.9"
socketio = "^5.8.0"
uvicorn = "^0.24.0"
```

## Examples

### Example 1: Simple Echo Server

```python
# See example_server.py
```

### Example 2: Interactive Client

```python
# See example_client.py
```

### Example 3: Agent Integration

```python
# See agent_socketio.py
```

## Testing

### Test Server

```bash
python Broca/comm/example_server.py
```

### Test Client

```bash
python Broca/comm/example_client.py cli
```

### Test Agent

```python
from Broca.agent_socketio import SocketIOAgent
from Broca.agent import AgentConfig
from Broca.llm import LLMClient

config = AgentConfig()
config.role_description = "You are a helpful assistant"
config.llm_config_name = "minimax"

llm_client = LLMClient()

agent = SocketIOAgent(
    config=config,
    llm_client=llm_client,
    server_url="http://localhost:8000",
    client_type="agent"
)

agent.run()
```

## Troubleshooting

### Connection Issues

1. **Server not running**: Make sure the server is running on the specified URL
2. **CORS issues**: Check CORS configuration on the server
3. **Network issues**: Ensure network connectivity between client and server

### Message Issues

1. **Message not received**: Check subscription/channel names
2. **Message format error**: Ensure message follows the correct format
3. **Message validation error**: Check message structure and required fields

### Reconnection Issues

1. **Auto-reconnect not working**: Check `auto_reconnect` parameter
2. **Reconnection delay**: Adjust `reconnect_delay` parameter
3. **Max attempts**: Increase `max_reconnect_attempts` if needed

## Future Enhancements

- [ ] WebSocket compression
- [ ] Message encryption
- [ ] Authentication and authorization
- [ ] Message persistence
- [ ] Rate limiting
- [ ] Message queuing
- [ ] Load balancing
- [ ] Cluster support
- [ ] Metrics and monitoring
- [ ] Message tracing

## License

This module is part of the Broca project and is licensed under the same license.

## Support

For issues and questions, please refer to the Broca project documentation or create an issue on the project repository.
