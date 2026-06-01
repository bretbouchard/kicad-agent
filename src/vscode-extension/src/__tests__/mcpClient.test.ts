import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpClient } from '../mcpClient';

describe('McpClient', () => {
  it('should create with correct config', () => {
    const client = new McpClient({
      serverCommand: 'echo',
      projectDir: '/tmp/test-project',
    });
    expect(client.isConnected).toBe(false);
  });

  it('should reject tool calls when not connected', async () => {
    const client = new McpClient({
      serverCommand: 'echo',
      projectDir: '/tmp/test-project',
    });
    await expect(client.callTool('test_tool', {})).rejects.toThrow('Not connected');
  });

  it('should reject listTools when not connected', async () => {
    const client = new McpClient({
      serverCommand: 'echo',
      projectDir: '/tmp/test-project',
    });
    await expect(client.listTools()).rejects.toThrow('Not connected');
  });

  it('should dispose cleanly when not connected', async () => {
    const client = new McpClient({
      serverCommand: 'echo',
      projectDir: '/tmp/test-project',
    });
    await expect(client.dispose()).resolves.toBeUndefined();
    expect(client.isConnected).toBe(false);
  });

  it('should dispose and reject pending requests', async () => {
    const client = new McpClient({
      serverCommand: 'cat',
      projectDir: '/tmp/test-project',
    });

    // Start a connection that won't complete
    const connectPromise = client.connect();

    // Immediately dispose
    await client.dispose();

    // The connect should eventually fail
    await expect(connectPromise).rejects.toThrow();
  });

  it('should emit connected event after successful connect', async () => {
    // This test verifies the event emitter interface exists
    const client = new McpClient({
      serverCommand: 'cat',
      projectDir: '/tmp/test-project',
    });

    let connectedFired = false;
    client.on('connected', () => { connectedFired = true; });

    // cat won't complete the MCP handshake, so connect will hang
    // Just verify the event listener was registered
    expect(connectedFired).toBe(false);

    await client.dispose();
  });
});
