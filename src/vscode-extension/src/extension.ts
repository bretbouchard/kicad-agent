/**
 * KiCad Agent VS Code extension entry point.
 *
 * Activates for .kicad_sch and .kicad_pcb files. Connects to the
 * kicad-agent-edit MCP server via stdio and provides:
 * - Context menu actions (Fix ERC, Suggest Improvements)
 * - Command palette commands (Run ERC, Run DRC, Visualize)
 * - Sidebar panels (Operation History, ERC Report)
 * - File watcher (auto-ERC on save)
 *
 * Security (threat model):
 *   T-54-01: Server command from extension config (user-controlled).
 *   T-54-02: Project directory scoped to workspace root.
 *   T-54-03: All file operations go through MCP server (sandboxed).
 */

import * as vscode from 'vscode';
import { McpClient } from './mcpClient';
import { runErc, runDrc, fixErc, suggestImprovements, visualize } from './operations';
import { HistoryProvider } from './sidebar/historyProvider';
import { ErcReportProvider } from './sidebar/ercReportProvider';
import { KiCadFileWatcher } from './watcher/fileWatcher';

let client: McpClient | null = null;
let history: HistoryProvider | null = null;
let ercReport: ErcReportProvider | null = null;
let watcher: KiCadFileWatcher | null = null;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration('kicad-agent');

  // Get workspace root for project directory
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!workspaceRoot) {
    vscode.window.showErrorMessage('KiCad Agent requires an open workspace');
    return;
  }

  // Initialize MCP client
  const serverCommand = config.get<string>('serverCommand', 'kicad-agent-edit');
  client = new McpClient({
    serverCommand,
    projectDir: workspaceRoot,
  });

  try {
    await client.connect();
  } catch (error) {
    vscode.window.showErrorMessage(
      `Failed to connect to kicad-agent server: ${error}. ` +
      'Ensure kicad-agent-edit is installed and in PATH.',
    );
    return;
  }

  // Initialize providers
  const maxHistory = config.get<number>('maxHistoryItems', 100);
  history = new HistoryProvider(maxHistory);
  ercReport = new ErcReportProvider();

  // File watcher
  const autoErc = config.get<boolean>('autoErcOnSave', true);
  watcher = new KiCadFileWatcher(client, history, ercReport, autoErc);

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('kicad-agent.runErc', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !editor.document.fileName.endsWith('.kicad_sch')) {
        vscode.window.showWarningMessage('Open a .kicad_sch file to run ERC');
        return;
      }
      await vscode.window.withProgress(
        { title: 'Running ERC...', location: vscode.ProgressLocation.Notification },
        async () => {
          const result = await runErc(client!, editor.document.fileName);
          ercReport!.updateFromReport(result);
          history!.addEntry({
            tool: 'validate_schematic',
            file: editor.document.fileName,
            result: result.pass ? 'pass' : `${result.violations.length} violations`,
          });
          if (result.pass) {
            vscode.window.showInformationMessage('ERC: No violations found');
          } else {
            vscode.window.showWarningMessage(`ERC: ${result.violations.length} violations found`);
          }
        },
      );
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('kicad-agent.runDrc', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !editor.document.fileName.endsWith('.kicad_pcb')) {
        vscode.window.showWarningMessage('Open a .kicad_pcb file to run DRC');
        return;
      }
      await vscode.window.withProgress(
        { title: 'Running DRC...', location: vscode.ProgressLocation.Notification },
        async () => {
          const result = await runDrc(client!, editor.document.fileName);
          history!.addEntry({
            tool: 'validate_pcb',
            file: editor.document.fileName,
            result: result.pass ? 'pass' : `${result.violations.length} violations`,
          });
          if (result.pass) {
            vscode.window.showInformationMessage('DRC: No violations found');
          } else {
            vscode.window.showWarningMessage(`DRC: ${result.violations.length} violations found`);
          }
        },
      );
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('kicad-agent.fixErc', async (uri?: vscode.Uri) => {
      const filePath = uri?.fsPath ?? vscode.window.activeTextEditor?.document.fileName;
      if (!filePath || !filePath.endsWith('.kicad_sch')) {
        vscode.window.showWarningMessage('Select a .kicad_sch file to fix ERC');
        return;
      }
      await vscode.window.withProgress(
        { title: 'Fixing ERC violations...', location: vscode.ProgressLocation.Notification },
        async () => {
          const result = await fixErc(client!, filePath);
          history!.addEntry({
            tool: 'erc_auto_fix',
            file: filePath,
            result: `Fixed ${result.fixed}, ${result.remaining} remaining`,
          });
          vscode.window.showInformationMessage(
            `ERC Fix: ${result.fixed} violations fixed, ${result.remaining} remaining`,
          );
        },
      );
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('kicad-agent.suggestImprovements', async (uri?: vscode.Uri) => {
      const filePath = uri?.fsPath ?? vscode.window.activeTextEditor?.document.fileName;
      if (!filePath) {
        vscode.window.showWarningMessage('Select a KiCad file');
        return;
      }
      await vscode.window.withProgress(
        { title: 'Analyzing design...', location: vscode.ProgressLocation.Notification },
        async () => {
          const result = await suggestImprovements(client!, filePath);
          history!.addEntry({
            tool: 'design_review',
            file: filePath,
            result: `${result.suggestions.length} suggestions`,
          });
          const channel = vscode.window.createOutputChannel('KiCad Agent');
          channel.clear();
          channel.appendLine(`Design Review: ${filePath}`);
          channel.appendLine('');
          result.suggestions.forEach((s, i) => {
            channel.appendLine(`${i + 1}. ${s}`);
          });
          channel.show();
        },
      );
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('kicad-agent.visualize', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      await vscode.window.withProgress(
        { title: 'Generating visualization...', location: vscode.ProgressLocation.Notification },
        async () => {
          const outputPath = await visualize(client!, editor.document.fileName);
          if (outputPath) {
            const uri = vscode.Uri.file(outputPath);
            await vscode.commands.executeCommand('vscode.open', uri);
          }
        },
      );
    }),
  );
}

export async function deactivate(): Promise<void> {
  watcher?.dispose();
  await client?.dispose();
  watcher = null;
  client = null;
  history = null;
  ercReport = null;
}
