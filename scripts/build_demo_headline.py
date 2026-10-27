#!/usr/bin/env python3
"""Build the demo-headline study: fan-chart plots and config.json.

Per participant: 2 practice trials, then 32 trials + 2 attention checks in a balanced
Latin-square order. Probability arm (p55 / p25) is between subjects.

  32 = fan (tight, wide) x headline group (ambiguous, none x2, unambiguous) x signal (4)
  signal r = E[A] / E[B]: E[A] is the fan midpoint (Option A's payoff), E[B] = p x 10%.
  Unambiguous headlines are negative at r < 1 and positive at r >= 1 (2 negative, 6 positive),
  and share topic and history trend with the ambiguous headline of the same fan x signal.

Each condition has 3 history trends. Three Latin-square lists rotate the trends, so across
lists every condition appears with every trend and, within a list, the two no-headline
copies never share a trend.

Run from the repo root with numpy + matplotlib:  python scripts/build_demo_headline.py
"""

import json
from itertools import product
from pathlib import Path
from urllib.parse import urlencode

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

STUDY = Path(__file__).resolve().parents[1] / 'public' / 'demo-headline'
PLOTS = STUDY / 'assets' / 'plots'

ARMS = {'p55': 0.55, 'p25': 0.25}          # Option B pays +10% with probability p
FANS = {'tight': 10, 'wide': 20}           # bull/bear half-width around E[A] (pp)
SIGNALS = [0.5, 1.0, 1.5, 2.0]             # r = E[A] / E[B]
GROUPS = ['amb', 'nh1', 'nh2', 'unamb']    # g in the trend rotation (f + g + s + list) % 3
TRENDS = ['positive', 'negative', 'flat']  # S1, S2, S3
NUM_LISTS = 3
TRIALS_PER_LIST = 34
ATTENTION = {  # E[A] far outside Option B's 0-10% band, tight fan
    'AC1': (24.0, 'attention_positive', 'optionA'),
    'AC2': (-14.0, 'attention_negative', 'optionB'),
}
PRACTICE_HALF = 6

# Headline pairs [list][fan * 4 + signal]: (domain, ambiguous, unambiguous valence, unambiguous).
# Each list (one participant) covers 8 distinct topics; no headline claims a recent price move,
# so none contradicts the history line it is paired with.
PAIRS = [
    [
        ('inflation',
         ('Inflation cools slightly, but the Fed signals rates will stay high for now',
          'Prices rose a little more slowly last month, yet officials said it is too early to cut interest rates.'),
         'negative',
         ('Inflation runs hotter than expected, dimming hopes for rate cuts',
          'Consumer prices rose faster than forecast, making it more likely that borrowing costs stay high.')),
        ('jobs',
         ('Hiring slows, but unemployment stays near historic lows',
          'Employers added fewer jobs than the month before, while the jobless rate barely changed.'),
         'positive',
         ('Employers add more jobs than expected as wages keep rising',
          'A strong monthly jobs report showed hiring across most industries.')),
        ('earnings',
         ('Company profits beat forecasts, but executives warn of a slower year ahead',
          'Many firms reported strong results while lowering their outlook for the coming months.'),
         'positive',
         ('Corporate profits beat forecasts across most industries',
          "Most large companies reported earnings above analysts' expectations this quarter.")),
        ('consumer',
         ('Shoppers keep spending even as credit card balances climb',
          'Spending held up last month, but more households are relying on borrowing.'),
         'positive',
         ('Consumer spending rises for a third straight month',
          'Households bought more goods and services, a sign of a healthy economy.')),
        ('retail',
         ('Holiday sales grow, but retailers rely on steep discounts',
          'Store sales rose from last year, though heavy price cuts squeezed profits.'),
         'negative',
         ('Retailers cut sales forecasts as shoppers pull back',
          'Several major chains said customers are buying less and lowered their outlooks.')),
        ('manufacturing',
         ('Factory orders rise, but manufacturers hold off on hiring',
          'New orders picked up last month while factories kept their workforces flat.'),
         'positive',
         ('Factory activity expands as new orders pick up',
          'A survey of manufacturers showed production and orders growing at a faster pace.')),
        ('banks',
         ('Banks report solid profits but set aside more money for bad loans',
          'Lenders earned more than expected while preparing for more borrowers to fall behind.'),
         'positive',
         ('Banks report strong profits as loan demand grows',
          'Major lenders said businesses and households are borrowing more, and few loans are going bad.')),
        ('small_business',
         ('Small business owners expect higher sales but worry about rising costs',
          'A monthly survey showed better sales expectations alongside concerns about wages and prices.'),
         'positive',
         ('Small business confidence climbs to its highest level in a year',
          'Owners reported stronger sales and more plans to hire and invest.')),
    ],
    [
        ('earnings',
         ('Earnings season delivers mixed results across industries',
          'About half of companies topped forecasts, while the rest reported weaker sales.'),
         'negative',
         ('Companies lower profit outlooks as demand weakens',
          'A growing number of firms said they expect slower sales and smaller profits next quarter.')),
        ('inflation',
         ('Fed holds rates steady and leaves the timing of cuts unclear',
          'Officials noted progress on inflation but gave no signal about when rates might come down.'),
         'positive',
         ('Inflation falls more than expected, raising hopes for lower rates',
          'Price growth slowed sharply last month, strengthening the case for interest rate cuts.')),
        ('jobs',
         ('Job openings fall while layoffs remain low',
          'Employers posted fewer openings, but few workers are being let go.'),
         'positive',
         ('Layoffs drop to their lowest level in months',
          'Fewer Americans filed for unemployment benefits, a sign the job market remains strong.')),
        ('consumer',
         ('Consumer confidence improves, but households still worry about prices',
          'Americans felt better about the economy while remaining concerned about the cost of living.'),
         'positive',
         ('Consumer confidence jumps as Americans feel better about jobs and income',
          'A monthly survey found households more optimistic about their finances and the economy.')),
        ('energy',
         ('Oil prices fall, but supply worries keep traders on edge',
          'Crude prices eased this week as markets watched for possible production cuts.'),
         'negative',
         ('Oil prices surge as supply cuts raise costs for businesses',
          'A jump in crude prices is expected to lift fuel costs and squeeze company profits.')),
        ('housing',
         ('Home sales rise, but high mortgage rates keep many buyers away',
          'More homes changed hands last month, though affordability remains a challenge.'),
         'positive',
         ('Home sales climb as mortgage rates ease',
          'Lower borrowing costs brought more buyers into the housing market last month.')),
        ('technology',
         ('Tech companies spend heavily on AI, but the payoff remains unclear',
          'Big investments in artificial intelligence boosted some suppliers while raising questions about future returns.'),
         'positive',
         ('Strong demand for AI chips lifts technology sales',
          'Major chip suppliers reported record orders and raised their forecasts.')),
        ('global',
         ('Exports rise, but trade tensions cloud the outlook',
          'Overseas sales grew last month as officials debated new tariffs.'),
         'positive',
         ('Trade deal eases tariff fears for businesses',
          'Negotiators agreed to lower tariffs, reducing costs for importers and exporters.')),
    ],
    [
        ('housing',
         ('Home prices keep rising even as sales slow',
          'Prices climbed again last month while fewer buyers made offers.'),
         'negative',
         ('Home sales fall to their lowest level in years as mortgage rates climb',
          'Rising borrowing costs pushed many buyers out of the market.')),
        ('energy',
         ('Gas prices drop, but heating bills are expected to rise this winter',
          'Drivers are paying less at the pump while utilities warn of higher energy costs.'),
         'positive',
         ('Gas prices fall, easing costs for drivers and businesses',
          'Lower fuel prices are expected to leave households and companies with more money to spend.')),
        ('technology',
         ('Software sales keep growing, but customers take longer to sign deals',
          'Tech firms still reported growth, though businesses are reviewing their budgets more carefully.'),
         'positive',
         ('Tech companies raise forecasts as businesses spend more on software',
          'Strong orders from corporate customers led several firms to lift their outlooks.')),
        ('global',
         ('Global economy sends mixed signals as Europe slows and Asia picks up',
          'Growth weakened in some major economies while improving in others.'),
         'positive',
         ('Global growth picks up as major economies strengthen',
          'New figures showed faster growth in Europe and Asia, supporting demand for U.S. goods.')),
        ('manufacturing',
         ('Factories produce more, but new orders slip',
          'Output rose last month while orders for future production declined.'),
         'negative',
         ('Factory activity shrinks for a third straight month',
          'Manufacturers reported falling orders and output, and some announced job cuts.')),
        ('banks',
         ('Banks tighten lending rules even as loans remain available',
          'Lenders are asking more of borrowers, though most businesses can still get credit.'),
         'positive',
         ('Banks ease lending standards as the economic outlook improves',
          'Lenders said they are more willing to make loans to businesses and consumers.')),
        ('retail',
         ('Online sales surge while store traffic slows',
          'Shoppers bought more on the internet but made fewer trips to stores.'),
         'positive',
         ('Retail sales beat expectations as shoppers spend more',
          'Sales at stores and online rose more than forecast last month.')),
        ('small_business',
         ('Small businesses plan to hire, but many struggle to find workers',
          'Owners want to add staff while reporting difficulty filling open positions.'),
         'positive',
         ('Small businesses step up hiring and investment',
          'Owners reported more job openings and plans to buy new equipment.')),
    ],
]

ATTENTION_HEADLINES = {  # one per history trend (S1, S2, S3)
    'AC1': [
        ('Economy strengthens across the board as growth, hiring, and profits all rise',
         'Every major economic report this week pointed in the same favorable direction.'),
        ('Inflation falls and job growth accelerates in a clearly positive report',
         'Economists said the latest data showed unusually strong and consistent improvement.'),
        ('Analysts sharply raise forecasts after a wave of strong economic data',
         'Nearly every major indicator beat expectations, creating an unusually clear positive outlook.'),
    ],
    'AC2': [
        ('Economy weakens across the board as growth, hiring, and profits all fall',
         'Every major economic report this week pointed in the same unfavorable direction.'),
        ('Inflation jumps and job losses mount in a clearly negative report',
         'Economists said the latest data showed unusually broad and consistent deterioration.'),
        ('Analysts sharply cut forecasts after a wave of weak economic data',
         'Nearly every major indicator missed expectations, creating an unusually clear negative outlook.'),
    ],
}

PRACTICE = [  # (E[A] %, correct, headline): one trial with a headline, one chart-only
    (11.5, 'optionA', {'id': 'practice-pos', 'valence': 'positive', 'domain': 'economy',
                       'headline': 'Economy grows faster than expected in latest report',
                       'lede': 'Strong spending by households and businesses lifted growth last quarter.'}),
    (-0.5, 'optionB', None),
]

CHOICE = {'id': 'investment-choice', 'prompt': 'Investment choice', 'type': 'reactive',
          'location': 'belowStimulus', 'required': True, 'hidden': True}
TRIAL_STYLE = {'maxWidth': '1100px', 'width': '100%', 'height': '780px', 'margin': '0 auto'}
BLUE, BLUE_FAN, GREEN = '#2166AC', '#4A90C2', '#2E7D32'


def history(trend, seed, days=60):
    """Recent return path ending at 0% today."""
    rng = np.random.RandomState(seed)
    start = {'positive': -8, 'negative': 8, 'flat': 0}[trend]
    path = np.linspace(start, 0, days) + np.cumsum(rng.randn(days) * 0.8) * 0.5
    return path - path[-1]


def plot(path, hist, ev_b, bull, bear):
    """Fan chart: history, bull/bear lines with shading, and Option B lines in green."""
    fig, ax = plt.subplots(figsize=(5.5, 3.5), dpi=150)
    x_fore = np.arange(61)
    bull_line, bear_line = np.linspace(0, bull, 61), np.linspace(0, bear, 61)
    for y, style, width, alpha in [(0, '-', 1.5, 0.85), (10, '-', 1.5, 0.85), (ev_b, '--', 1.2, 0.7)]:
        ax.axhline(y, color=GREEN, linewidth=width, linestyle=style, alpha=alpha, zorder=1)
    ax.fill_between(x_fore, bear_line, bull_line, color=BLUE_FAN, alpha=0.18, zorder=2)
    ax.plot(np.arange(-len(hist), 0), hist, color=BLUE, linewidth=1.5, zorder=4)
    for line in (bear_line, bull_line):
        ax.plot(x_fore, line, color=BLUE, linewidth=1.5, linestyle='--', zorder=3)
    ax.axvline(0, color='gray', linewidth=0.8, linestyle=':', alpha=0.6)
    ax.text(0.5, 37, 'Today', fontsize=7, color='gray', ha='left', va='top')
    ax.axhline(0, color='gray', linewidth=0.5, alpha=0.4, zorder=1)
    ax.set_xlim(-62, 62)
    ax.set_ylim(-40, 40)
    ax.set_xticks(np.arange(-60, 61, 10))
    ax.set_xlabel('Day (0 = today)', fontsize=9)
    ax.set_ylabel('Investment Return (%)', fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%+.0f%%'))
    ax.tick_params(labelsize=7)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def trial(arm, name, base, half, trend, seed, headline, meta):
    p = ARMS[arm]
    ev_b = round(p * 10, 4)
    bull, bear = round(base + half, 4), round(base - half, 4)
    chart = f'{name}.png'
    plot(PLOTS / chart, history(trend, seed), ev_b, bull, bear)
    query = {'c': chart, 'sig': f'{base:g}'}
    if headline:
        query.update(hid=headline['id'], h=headline['headline'], l=headline['lede'],
                     sent=headline['valence'], domain=headline['domain'])
    if meta.get('isPractice'):
        query['practice'] = 1
    query['p'] = p  # keep last: older reVISit builds append "?trialid=..." to the final value
    return {
        'type': 'website',
        'path': 'demo-headline/assets/trial-stimulus.html?' + urlencode(query),
        'nextButtonLocation': 'belowStimulus',
        'meta': {
            'trial_id': name, 'chart_file': chart, 'probability_arm': arm,
            'option_b_probability': p, 'option_b_expected_return_pct': ev_b,
            'base_target_pct': base, 'bull_target_pct': bull, 'bear_target_pct': bear,
            'history_trend': trend,
            'headline_id': headline and headline['id'],
            'headline_valence': headline and headline['valence'],
            'headline_domain': headline and headline['domain'],
            'headline_text': headline and headline['headline'],
            'headline_lede': headline and headline['lede'],
            **meta,
        },
        'response': [CHOICE],
        'style': TRIAL_STYLE,
    }


def pair_headline(k, pos, group):
    domain, (amb_h, amb_l), valence, (h, l) = PAIRS[k][pos]
    if group == 'amb':
        return {'id': f'L{k + 1}-{pos + 1}-amb', 'valence': 'ambiguous', 'domain': domain,
                'headline': amb_h, 'lede': amb_l}
    return {'id': f'L{k + 1}-{pos + 1}-{valence[:3]}', 'valence': valence, 'domain': domain,
            'headline': h, 'lede': l}


def main_name(arm, f, g, s, t):
    return f'{arm}-{list(FANS)[f]}-{GROUPS[g]}-r{round(SIGNALS[s] * 100):03d}-S{t + 1}'


def arm_components(arm):
    ev_b = round(ARMS[arm] * 10, 4)
    comps = {
        f'{arm}-introduction': {
            'type': 'markdown', 'path': f'demo-headline/assets/introduction-{arm}.md',
            'nextButtonText': 'Continue', 'response': [],
            'style': {'maxWidth': '900px', 'width': '100%', 'margin': '0 auto'},
            'meta': {'probability_arm': arm},
        },
        f'{arm}-risk-precheck': {
            'type': 'website', 'path': f'demo-headline/assets/risk-precheck.html?p={arm[1:]}',
            'nextButtonLocation': 'belowStimulus',
            'response': [{'id': f'risk-precheck-{arm}-complete', 'prompt': 'Risk preference questions complete',
                          'type': 'reactive', 'location': 'belowStimulus', 'required': True,
                          'hidden': True, 'requiredValue': True}],
            'style': {'maxWidth': '780px', 'width': '100%', 'height': '700px', 'margin': '0 auto'},
            'meta': {'probability_arm': arm},
        },
    }
    for i, (base, correct, headline) in enumerate(PRACTICE, 1):
        name = f'{arm}-practice-{i}'
        comps[name] = trial(arm, name, base, PRACTICE_HALF, 'flat', 9900 + i, headline,
                            {'isPractice': True, 'correct': correct})
    for (f, fan), (g, group), (s, r), t in product(enumerate(FANS), enumerate(GROUPS),
                                                    enumerate(SIGNALS), range(3)):
        k = (t - f - g - s) % NUM_LISTS
        headline = pair_headline(k, f * 4 + s, group) if group in ('amb', 'unamb') else None
        name = main_name(arm, f, g, s, t)
        comps[name] = trial(arm, name, round(r * ev_b, 4), FANS[fan], TRENDS[t],
                            1000 + 10 * (16 * f + 4 * g + s) + t, headline, {
                                'condition_id': name[len(arm) + 1:-3], 'fan_width': fan,
                                'headline_group': {'amb': 'ambiguous', 'unamb': 'unambiguous'}.get(group, 'none'),
                                'signal_ratio': r, 'list': k + 1,
                                'correct': 'optionA' if r > 1 else 'optionB' if r < 1 else 'tie',
                                'is_attention_check': False,
                            })
    for a, (ac, (base, valence, correct)) in enumerate(ATTENTION.items()):
        for t in range(3):
            h, l = ATTENTION_HEADLINES[ac][t]
            name = f'{arm}-{ac}-S{t + 1}'
            comps[name] = trial(arm, name, base, FANS['tight'], TRENDS[t], 99000 + 10 * (a + 1) + t + 1,
                                {'id': f'{ac}-{t + 1}', 'valence': valence, 'domain': 'attention',
                                 'headline': h, 'lede': l}, {
                                    'condition_id': ac, 'fan_width': 'tight', 'headline_group': 'attention',
                                    'signal_ratio': round(base / ev_b, 3), 'list': (t - a) % NUM_LISTS + 1,
                                    'correct': correct, 'is_attention_check': True,
                                })
    return comps


def arm_block(arm):
    lists = []
    for k in range(NUM_LISTS):
        names = [main_name(arm, f, g, s, (f + g + s + k) % NUM_LISTS)
                 for f, g, s in product(range(len(FANS)), range(len(GROUPS)), range(len(SIGNALS)))]
        names += [f'{arm}-{ac}-S{(k + a) % NUM_LISTS + 1}' for a, ac in enumerate(ATTENTION)]
        assert len(names) == TRIALS_PER_LIST
        lists.append({'id': f'{arm}-list-{k + 1}', 'order': 'latinSquare', 'components': names})
    return {'id': f'probability-arm-{arm}', 'order': 'fixed', 'components': [
        f'{arm}-introduction', f'{arm}-risk-precheck', f'{arm}-practice-1', f'{arm}-practice-2',
        {'id': f'{arm}-lists', 'order': 'latinSquare', 'numSamples': 1, 'components': lists},
    ]}


def main():
    for k, pairs in enumerate(PAIRS):
        assert len({d for d, *_ in pairs}) == 8, f'list {k + 1} repeats a topic'
        assert [v for _, _, v, _ in pairs] == ['negative', 'positive', 'positive', 'positive'] * 2
    texts = [h for pairs in PAIRS for _, (a, _), _, (h, _) in pairs for h in (a, h)]
    texts += [h for ac in ATTENTION_HEADLINES.values() for h, _ in ac]
    assert len(set(texts)) == len(texts), 'duplicate headline text'

    config_path = STUDY / 'config.json'
    old = json.loads(config_path.read_text())
    for png in PLOTS.glob('*.png'):
        png.unlink()

    components = {name: old['components'][name]
                  for name in ['consent', 'post-study-free-response', 'post-study-survey', 'debrief']}
    for arm in ARMS:
        components.update(arm_components(arm))

    old['studyMetadata'].update(
        version='5.0.0-p55-p25-latin-square', date='2026-10-26',
        description='Examines how news headlines, headline ambiguity, and forecast uncertainty influence '
                    'investment choices, with balanced assignment to 55% and 25% probability arms.')
    # One full balanced Latin square of trial orders for every arm x list.
    old['uiConfig']['numSequences'] = len(ARMS) * NUM_LISTS * TRIALS_PER_LIST
    old['components'] = components
    old['sequence'] = {'order': 'fixed', 'components': [
        'consent',
        {'order': 'latinSquare', 'numSamples': 1, 'components': [arm_block(arm) for arm in ARMS]},
        'post-study-free-response', 'post-study-survey', 'debrief',
    ]}
    config_path.write_text(json.dumps(old, indent=2, ensure_ascii=False) + '\n')
    print(f'{len(components)} components, {len(list(PLOTS.glob("*.png")))} plots')


if __name__ == '__main__':
    main()
