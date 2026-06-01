import { describe, it, expect } from 'vitest';
import { HistoryProvider } from '../sidebar/historyProvider';

describe('HistoryProvider', () => {
  it('should track operations with timestamps', () => {
    const provider = new HistoryProvider(100);
    provider.addEntry({ tool: 'validate_schematic', file: 'test.kicad_sch', result: 'pass' });
    const entries = provider.getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].tool).toBe('validate_schematic');
    expect(entries[0].timestamp).toBeDefined();
  });

  it('should limit history to maxItems', () => {
    const provider = new HistoryProvider(5);
    for (let i = 0; i < 10; i++) {
      provider.addEntry({ tool: `tool_${i}`, file: 'test.kicad_sch', result: 'ok' });
    }
    expect(provider.getEntries()).toHaveLength(5);
    // Should keep the most recent
    expect(provider.getEntries()[0].tool).toBe('tool_5');
  });

  it('should clear history', () => {
    const provider = new HistoryProvider(100);
    provider.addEntry({ tool: 'validate_schematic', file: 'test.kicad_sch', result: 'pass' });
    provider.clear();
    expect(provider.getEntries()).toHaveLength(0);
  });

  it('should report count', () => {
    const provider = new HistoryProvider(100);
    expect(provider.count).toBe(0);
    provider.addEntry({ tool: 'validate_schematic', file: 'test.kicad_sch', result: 'pass' });
    expect(provider.count).toBe(1);
  });
});
