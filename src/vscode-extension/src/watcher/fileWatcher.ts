/**
 * File system watcher for auto-ERC on save.
 *
 * Watches .kicad_sch files for save events and triggers
 * ERC validation when autoErcOnSave is enabled.
 */

import { McpClient } from '../mcpClient';
import { runErc } from '../operations';
import { HistoryProvider } from '../sidebar/historyProvider';
import { ErcReportProvider } from '../sidebar/ercReportProvider';

export class KiCadFileWatcher {
  private readonly client: McpClient;
  private readonly history: HistoryProvider;
  private readonly ercReport: ErcReportProvider;
  private enabled: boolean;

  constructor(
    client: McpClient,
    history: HistoryProvider,
    ercReport: ErcReportProvider,
    enabled: boolean = true,
  ) {
    this.client = client;
    this.history = history;
    this.ercReport = ercReport;
    this.enabled = enabled;
  }

  async onFileChanged(filePath: string): Promise<void> {
    if (!this.enabled) return;
    if (!filePath.endsWith('.kicad_sch')) return;

    try {
      const result = await runErc(this.client, filePath);
      this.ercReport.updateFromReport(result);
      this.history.addEntry({
        tool: 'validate_schematic',
        file: filePath,
        result: result.pass ? 'pass' : `${result.violations.length} violations`,
      });
    } catch {
      // Silently ignore ERC errors during auto-save
    }
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  dispose(): void {
    // Cleanup if needed
  }
}
