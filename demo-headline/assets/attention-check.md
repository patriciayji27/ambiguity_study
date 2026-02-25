# Attention Check Design

## Purpose
The attention check verifies that participants are reading instructions and responding thoughtfully rather than clicking randomly.

## Implementation
The attention check is embedded among the 32 main trials in a randomized position. It uses the same visual format as regular trials (chart + Option A/B choice) so that it does not visually stand out.

## Question Design
The attention check displays a chart stimulus identical in format to regular trials, but the instruction text explicitly states:

> "This is an attention check. Please read the options carefully. Regardless of what the chart shows, **please select Option B** below."

### Correct Answer
Participants who are reading the instructions should select **Option B**.

### Failure Criteria
Participants who select Option A on this question may not be reading the instructions carefully. This can be used as a data quality filter during analysis.

## Rationale
This approach follows common practices in online behavioral studies (e.g., Oppenheimer, Meyvis, & Davidenko, 2009). By embedding the check within the normal trial flow and maintaining the same visual format, we minimize disruption while reliably detecting inattentive responding.

The instruction-following format (rather than a trick question) is preferred because:
1. It tests attention directly without requiring domain knowledge.
2. It does not penalize participants who have different interpretations of ambiguous stimuli.
3. It maps cleanly to a binary pass/fail criterion for data filtering.
