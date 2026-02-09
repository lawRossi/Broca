"""
Example Socket.io Server

This is an example server that demonstrates how to use the Socket.io communication module.
"""

import asyncio
import logging

from Broca.comm.message_types import Message, MessageProtocol
from Broca.comm.socketio_server import SocketIOServer

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Main function to run the example server"""

    # Create Socket.io server
    server = SocketIOServer(host="0.0.0.0", port=8001, cors_allowed_origins="*")

    # Register event handlers
    @server.on("connect")
    async def on_connect(client_info):
        logger.info(
            f"Client connected: {client_info.client_id} ({client_info.client_type})"
        )

    @server.on("disconnect")
    async def on_disconnect(client_info):
        logger.info(f"Client disconnected: {client_info.client_id}")

    @server.on("user_message")
    async def on_user_message(client_info, message: Message):
        logger.info(
            f"User message from {client_info.client_id}: {message.data.get('content')}"
        )

    @server.on("agent_response")
    async def on_agent_response(client_info, message: Message):
        pass

    @server.on("tool_call")
    async def on_tool_call(client_info, message: Message):
        logger.info(
            f"Tool call from {client_info.client_id}: {message.data.get('tool_name')}"
        )

    @server.on("command")
    async def on_command(client_info, message: Message):
        logger.info(
            f"Command from {client_info.client_id}: {message.data.get('command')}"
        )

        command = message.data.get("command")

        if command == "list_clients":
            # List all connected clients
            clients = server.get_clients()
            result_msg = MessageProtocol.create_command_result(
                command=command,
                result=clients,
                sender_id="server",
                receiver_id=client_info.client_id,
            )
            await server.send_message(result_msg, client_id=client_info.client_id)

        elif command == "list_subscriptions":
            # List all subscriptions
            subscriptions = server.get_subscriptions()
            result_msg = MessageProtocol.create_command_result(
                command=command,
                result=subscriptions,
                sender_id="server",
                receiver_id=client_info.client_id,
            )
            await server.send_message(result_msg, client_id=client_info.client_id)

        elif command == "broadcast":
            # Broadcast message
            content = message.data.get("arguments", {}).get("content", "")
            subscription = message.data.get("arguments", {}).get("subscription")

            await server.broadcast(content, subscription=subscription)

            result_msg = MessageProtocol.create_command_result(
                command=command,
                result=f"Broadcasted to {subscription or 'all clients'}",
                sender_id="server",
                receiver_id=client_info.client_id,
            )
            await server.send_message(result_msg, client_id=client_info.client_id)

    @server.on("broadcast")
    async def on_broadcast(client_info, message: Message):
        logger.info(
            f"Broadcast from {client_info.client_id}: {message.data.get('content')}"
        )

    # Start server
    logger.info("Starting Socket.io server on http://0.0.0.0:8000")
    logger.info("Available endpoints:")
    logger.info("  - WebSocket: ws://localhost:8000")
    logger.info("  - HTTP: http://localhost:8000")
    logger.info("")
    logger.info("Example commands:")
    logger.info("  - list_clients: List all connected clients")
    logger.info("  - list_subscriptions: List all subscriptions")
    logger.info("  - broadcast: Broadcast message to all clients")
    logger.info("")
    logger.info("Press Ctrl+C to stop the server")

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
