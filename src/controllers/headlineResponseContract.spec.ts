import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';

type ResponseConfig = {
  hidden?: boolean;
  id: string;
  required?: boolean;
  requiredValue?: unknown;
  type: string;
};

type ComponentConfig = {
  path?: string;
  response?: ResponseConfig[];
  type: string;
};

type HeadlineConfig = {
  components: Record<string, ComponentConfig>;
};

const repoRoot = process.cwd();
const studyRoot = resolve(repoRoot, 'public/demo-headline');
const config = JSON.parse(
  readFileSync(resolve(studyRoot, 'config.json'), 'utf8'),
) as HeadlineConfig;

const trialComponents = Object.entries(config.components)
  .filter(([, component]) => (
    component.type === 'website'
    && component.path?.includes('trial-stimulus.html')
  ));

const trialHtmlPaths = [
  resolve(studyRoot, 'assets/trial-stimulus.html'),
  resolve(studyRoot, 'assets-p75/trial-stimulus.html'),
];

const riskContracts = [
  {
    componentId: 'p55-risk-precheck',
    responseId: 'risk-precheck-p55-complete',
    htmlPath: resolve(studyRoot, 'assets/risk-precheck.html'),
  },
  {
    componentId: 'p75-risk-precheck',
    responseId: 'risk-precheck-p75-complete',
    htmlPath: resolve(studyRoot, 'assets-p75/risk-precheck.html'),
  },
];

function hasRequiredReactiveResponse(component: ComponentConfig, responseId: string) {
  return component.response?.some((response) => (
    response.id === responseId
    && response.type === 'reactive'
    && response.required === true
    && response.hidden === true
  ));
}

describe('demo-headline HTML response contract', () => {
  test('every p55 and p75 trial declares the investment choice reactive response', () => {
    expect(trialComponents).toHaveLength(196);

    trialComponents.forEach(([componentId, component]) => {
      expect(
        hasRequiredReactiveResponse(component, 'investment-choice'),
        `${componentId} must declare the investment-choice reactive response`,
      ).toBe(true);
    });
  });

  test.each(trialHtmlPaths)('%s posts the choice and payoff through ReVISit', (htmlPath) => {
    const html = readFileSync(htmlPath, 'utf8');

    expect(html).toContain('../../revisitUtilities/revisit-communicate.js');
    expect(html).toContain("'investment-choice':");
    expect(html).toContain("'trial-payoff':");
    expect(html).toContain('window.Revisit.postAnswers(answers)');
    expect(html).toContain("type: '@REVISIT_COMMS/ANSWERS'");
  });

  test.each(riskContracts)(
    '$componentId declares and posts its completion response with the full JSON record',
    ({ componentId, responseId, htmlPath }) => {
      const component = config.components[componentId];
      const html = readFileSync(htmlPath, 'utf8');

      expect(hasRequiredReactiveResponse(component, responseId)).toBe(true);
      expect(component.response?.find((response) => response.id === responseId)?.requiredValue).toBe(true);
      expect(html).toContain('../../revisitUtilities/revisit-communicate.js');
      expect(html).toContain('postAnswers(buildAnswers(true))');
      expect(html).toContain('window.Revisit.postAnswers(answers)');
      expect(html).toContain('ANSWER_PREFIX}-json');
    },
  );
});
