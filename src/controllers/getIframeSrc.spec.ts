import { describe, expect, test } from 'vitest';
import { getIframeSrc } from './getIframeSrc';

describe('getIframeSrc', () => {
  test('adds controller parameters to a path without query parameters', () => {
    expect(getIframeSrc(
      '/demo-headline/assets/trial-stimulus.html',
      'p55-hl-C01-S1',
      'iframe-1',
    )).toBe('/demo-headline/assets/trial-stimulus.html?trialid=p55-hl-C01-S1&id=iframe-1');
  });

  test('preserves existing study parameters instead of starting a second query string', () => {
    expect(getIframeSrc(
      '/demo-headline/assets/trial-stimulus.html?p=0.55&ev=5.5',
      'p55-hl-C01-S1',
      'iframe-2',
    )).toBe('/demo-headline/assets/trial-stimulus.html?p=0.55&ev=5.5&trialid=p55-hl-C01-S1&id=iframe-2');
  });

  test('keeps controller parameters before a URL fragment', () => {
    expect(getIframeSrc(
      'https://example.com/stimulus.html?p=0.75#choice',
      'p75-hl-C01-S1',
      'iframe-3',
    )).toBe('https://example.com/stimulus.html?p=0.75&trialid=p75-hl-C01-S1&id=iframe-3#choice');
  });
});
