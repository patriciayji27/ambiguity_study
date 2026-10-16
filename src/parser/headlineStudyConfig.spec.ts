import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { parseStudyConfig } from './parser';
import { ComponentBlock, StudyConfig, WebsiteComponent } from './types';

// Guards the headline studies: answers from their HTML (website) components are only stored
// when the HTML loads revisit-communicate.js and the config declares the posted reactive key.
const publicDir = fileURLToPath(new URL('../../public/', import.meta.url));

function htmlFile(component: WebsiteComponent) {
  return resolve(publicDir, component.path.split('?')[0]);
}

describe.each([
  // Merged study: 2 arms x (2 practice + 32 cells x 3 sentiment variants)
  {
    configPath: 'demo-headline/config.json', htmlFiles: 4, trials: 196, prechecks: ['p55-risk-precheck', 'p75-risk-precheck'],
  },
  // Standalone 75% study: 2 practice + 32 cells x 3 sentiment variants
  {
    configPath: 'demo-headline-p75/config.json', htmlFiles: 2, trials: 98, prechecks: ['risk-precheck-p75'],
  },
])('$configPath', ({
  configPath, htmlFiles, trials: trialCount, prechecks: precheckNames,
}) => {
  const rawConfig = readFileSync(resolve(publicDir, configPath), 'utf-8');
  const config = JSON.parse(rawConfig) as StudyConfig;

  const websiteComponents = Object.entries(config.components)
    .filter((entry): entry is [string, WebsiteComponent] => entry[1].type === 'website');

  test('passes reVISit config validation', async () => {
    const parsed = await parseStudyConfig(rawConfig);
    expect(parsed.errors).toEqual([]);
  });

  test('every HTML page loads revisit-communicate.js from a path that exists', () => {
    const files = new Set(websiteComponents.map(([, component]) => htmlFile(component)));
    expect(files.size).toBe(htmlFiles);

    files.forEach((file) => {
      const html = readFileSync(file, 'utf-8');
      const src = html.match(/<script src="([^"]*revisit-communicate\.js)"><\/script>/)?.[1];
      expect(src, file).toBeDefined();
      expect(existsSync(resolve(dirname(file), src || '')), `${file} -> ${src}`).toBe(true);
    });
  });

  test('trial components require the investment choice posted by trial-stimulus.html', () => {
    const trials = websiteComponents.filter(([, component]) => component.path.includes('trial-stimulus.html'));
    expect(trials).toHaveLength(trialCount);

    trials.forEach(([name, component]) => {
      expect(component.response, name).toEqual([expect.objectContaining({
        id: 'investment-choice', type: 'reactive', required: true, hidden: true,
      })]);
    });

    new Set(trials.map(([, component]) => htmlFile(component))).forEach((file) => {
      expect(readFileSync(file, 'utf-8')).toContain("'investment-choice':");
    });
  });

  test('risk precheck components require the completion key posted by risk-precheck.html', () => {
    const prechecks = websiteComponents.filter(([, component]) => component.path.includes('risk-precheck.html'));
    expect(prechecks.map(([name]) => name).sort()).toEqual(precheckNames);

    prechecks.forEach(([name, component]) => {
      // risk-precheck.html derives its answer keys from the ?p= parameter
      const arm = `p${component.path.match(/\?p=(\d+)/)?.[1]}`;
      expect(component.response, name).toEqual([expect.objectContaining({
        id: `risk-precheck-${arm}-complete`, type: 'reactive', required: true, hidden: true,
      })]);

      const html = readFileSync(htmlFile(component), 'utf-8');
      expect(html).toMatch(/const ANSWER_PREFIX = `risk-precheck-\$\{probabilityLevel\}`;/);
      expect(html).toMatch(/\[`\$\{ANSWER_PREFIX\}-complete`\]: !!finalFlag/);
    });
  });

  test('final page collects the Prolific ID', () => {
    const { components } = config.sequence as ComponentBlock;
    expect(components[components.length - 1]).toBe('debrief');
    expect(config.components.debrief.response).toContainEqual(expect.objectContaining({
      id: 'prolific_id', type: 'shortText', required: true, paramCapture: 'PROLIFIC_PID',
    }));
  });
});
