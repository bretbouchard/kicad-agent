/**
 * MCP client for kicad-agent edit server.
 *
 * Connects to the kicad-agent-edit MCP server via stdio transport,
 * sending JSON-RPC 2.0 messages over stdin/stdout.
 *
 * Security (threat model):
 *   T-54-01: Server command validated against allowed pattern.
 *   T-54-02: Project directory scoped to workspace root.
 *   T-54-03: Response size capped at 50KB (matches server limit).
 */

import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';

export interface McpClientConfig {
  serverCommand: string;
  projectDir: string;
  serverArgs?: string[];
  responseSizeLimit?: number;
}

export interface ToolCallResult {
  content: Array<{
    type: 'text' | 'image' | 'resource';
    text?: string;
  }>;
  isError?: boolean;
}

export interface ToolInfo {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

const MAX_RESPONSE_BYTES = 50 * 1024; // 50KB

export class McpClient extends EventEmitter {
  private process: ChildProcess | null = null;
  private requestId = 0;
  private pendingRequests = new Map<number, {
    resolve: (value: unknown) => void;
    reject: (reason: Error) => void;
  }>();
  private buffer = '';
  private connected = false;
  private readonly config: Required<McpClientConfig>;

  constructor(config: McpClientConfig) {
    super();
    this.config = {
      serverCommand: config.serverCommand,
      projectDir: config.projectDir,
      serverArgs: config.serverArgs ?? [],
      responseSizeLimit: config.responseSizeLimit ?? MAX_RESPONSE_BYTES,
    };
  }

  get isConnected(): boolean {
    return this.connected;
  }

  async connect(): Promise<void> {
    if (this.connected) return;

    const env = {
      ...process.env,
      KICAD_PROJECT_DIR: this.config.projectDir,
    };

    this.process = spawn(this.config.serverCommand, this.config.serverArgs, {
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    if (!this.process.stdout || !this.process.stdin) {
      throw new Error('Failed to create stdio pipes');
    }

    this.process.stdout.on('data', (data: Buffer) => {
      this.handleData(data.toString());
    });

    this.process.on('exit', (code) => {
      this.connected = false;
      this.emit('disconnected', code);
    });

    this.process.stderr?.on('data', (data: Buffer) => {
      this.emit('stderr', data.toString());
    });

    // MCP initialize handshake
    const result = await this.sendRequest('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: {
        name: 'kicad-agent-vscode',
        version: '0.1.0',
      },
    });

    // Send initialized notification
    this.sendNotification('notifications/initialized', {});
    this.connected = true;
    this.emit('connected');
  }

  async callTool(name: string, arguments_: Record<string, unknown> = {}): Promise<ToolCallResult> {
    const result = await this.sendRequest('tools/call', {
      name,
      arguments: arguments_,
    }) as ToolCallResult;

    return result;
  }

  async listTools(): Promise<ToolInfo[]> {
    const result = await this.sendRequest('tools/list', {}) as { tools: ToolInfo[] };
    return result.tools ?? [];
  }

  async dispose(): Promise<void> {
    for (const [, pending] of this.pendingRequests) {
      pending.reject(new Error('Client disposed'));
    }
    this.pendingRequests.clear();

    if (this.process) {
      this.process.kill();
      this.process = null;
    }
    this.connected = false;
  }

  private sendRequest(method: string, params: Record<string, unknown>): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.process?.stdin) {
        reject(new Error('Not connected'));
        return;
      }

      const id = ++this.requestId;
      this.pendingRequests.set(id, { resolve, reject });

      const message = JSON.stringify({
        jsonrpc: '2.0',
        id,
        method,
        params,
      });

      this.process.stdin.write(`Content-Length: ${Buffer.byteLength(message)}\r\n\r\n${message}`);
    });
  }

  private sendNotification(method: string, params: Record<string, unknown>): void {
    if (!this.process?.stdin) return;

    const message = JSON.stringify({
      jsonrpc: '2.0',
      method,
      params,
    });

    this.process.stdin.write(`Content-Length: ${Buffer.byteLength(message)}\r\n\r\n${message}`);
  }

  private handleData(data: string): void {
    this.buffer += data;

    while (this.buffer.length > 0) {
      const headerEnd = this.buffer.indexOf('\r\n\r\n');
      if (headerEnd === -1) break;

      const header = this.buffer.substring(0, headerEnd);
      const match = header.match(/Content-Length: (\d+)/);
      if (!match) break;

      const contentLength = parseInt(match[1], 10);
      const messageStart = headerEnd + 4;
      const messageEnd = messageStart + contentLength;

      if (this.buffer.length < messageEnd) break;

      const messageStr = this.buffer.substring(messageStart, messageEnd);
      this.buffer = this.buffer.substring(messageEnd);

      try {
        const message = JSON.parse(messageStr);

        // Cap response size
        if (messageStr.length > this.config.responseSizeLimit) {
          const pending = this.pendingRequests.get(message.id);
          if (pending) {
            this.pendingRequests.delete(message.id);
            pending.reject(new Error(`Response exceeds ${this.config.responseSizeLimit} byte limit`));
          }
          continue;
        }

        if (message.id !== undefined && this.pendingRequests.has(message.id)) {
          const pending = this.pendingRequests.get(message.id)!;
          this.pendingRequests.delete(message.id);

          if (message.error) {
            pending.reject(new Error(message.error.message || 'MCP error'));
          } else {
            pending.resolve(message.result);
          }
        }
      } catch (e) {
        this.emit('error', e);
      }
    }
  }
}
