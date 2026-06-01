/**
 * High-level operation wrappers for kicad-agent MCP tools.
 *
 * Maps user-facing actions (Run ERC, Fix ERC, etc.) to MCP tool calls.
 */

import { McpClient, ToolCallResult } from './mcpClient';

export interface ErcResult {
  pass: boolean;
  violations: Array<{
    type: string;
    severity: string;
    description: string;
    position?: { x: number; y: number };
  }>;
  raw?: string;
}

export interface DrcResult {
  pass: boolean;
  violations: Array<{
    type: string;
    description: string;
  }>;
  raw?: string;
}

export interface FixResult {
  fixed: number;
  remaining: number;
  details?: string;
}

export interface ReviewResult {
  suggestions: string[];
  raw?: string;
}

function parseContent(result: ToolCallResult): string {
  const textContent = result.content.find(c => c.type === 'text');
  return textContent?.text ?? '';
}

export async function runErc(client: McpClient, filePath: string): Promise<ErcResult> {
  const result = await client.callTool('validate_schematic', { path: filePath });
  const text = parseContent(result);

  try {
    const parsed = JSON.parse(text);
    return {
      pass: parsed.pass ?? false,
      violations: parsed.violations ?? [],
      raw: text,
    };
  } catch {
    return {
      pass: false,
      violations: [],
      raw: text,
    };
  }
}

export async function runDrc(client: McpClient, filePath: string): Promise<DrcResult> {
  const result = await client.callTool('validate_pcb', { path: filePath });
  const text = parseContent(result);

  try {
    const parsed = JSON.parse(text);
    return {
      pass: parsed.pass ?? false,
      violations: parsed.violations ?? [],
      raw: text,
    };
  } catch {
    return {
      pass: false,
      violations: [],
      raw: text,
    };
  }
}

export async function fixErc(client: McpClient, filePath: string): Promise<FixResult> {
  const result = await client.callTool('erc_auto_fix', { path: filePath });
  const text = parseContent(result);

  try {
    const parsed = JSON.parse(text);
    return {
      fixed: parsed.fixed ?? 0,
      remaining: parsed.remaining ?? 0,
      details: text,
    };
  } catch {
    return {
      fixed: 0,
      remaining: -1,
      details: text,
    };
  }
}

export async function suggestImprovements(client: McpClient, filePath: string): Promise<ReviewResult> {
  const result = await client.callTool('design_review', { path: filePath });
  const text = parseContent(result);

  try {
    const parsed = JSON.parse(text);
    return {
      suggestions: parsed.suggestions ?? [],
      raw: text,
    };
  } catch {
    return {
      suggestions: [],
      raw: text,
    };
  }
}

export async function visualize(client: McpClient, filePath: string): Promise<string | null> {
  const isPcb = filePath.endsWith('.kicad_pcb');
  const tool = isPcb ? 'export_3d_render' : 'export_schematic_pdf';
  const result = await client.callTool(tool, { path: filePath });
  const text = parseContent(result);
  return text || null;
}
