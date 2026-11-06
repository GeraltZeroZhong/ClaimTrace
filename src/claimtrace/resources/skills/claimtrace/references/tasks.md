# Molecular figure tasks

These examples describe how to choose relevant evidence. All values and
identifiers come from the user's files or actual analysis. Adapt the scope to
the stated claim.

## Ligand contacts

**Request:** “Check whether this panel supports the claimed ligand contacts.”

Inspect the figure, native scene and structure, then locate the ligand, pocket
selection and any contact table or measurement record. Read the recorded atom
identities, distance rule, cutoff, units, model/state and alternative-location
handling that affect the result.

When a table is supplied, report its observation and method as supplied. When
the user requests a new calculation and an appropriate tool is available,
perform it and attach its output. Keep proximity, interaction assignment and
pose support distinct in the claim wording.

**Useful next step:** obtain the missing cutoff or link the existing contact
table to the selected claim. A plausible-looking contact alone leaves its
measurement and interpretation open.

## Density support

**Request:** “Does the density support this ligand pose?”

Locate the coordinate model, map, relevant region, contour level and units,
processing information and local fit evidence. Read available alternative poses
or threshold comparisons. Identify which map and contour generated the panel.

If only an image is available, describe its visible context and the inputs
needed for a density assessment. A contact analysis answers a separate question
from density support. Record threshold sensitivity when the supplied evidence
or an actual comparison establishes it.

**Useful next step:** attach the map and its contour provenance, or connect the
supplied local validation result to the pose claim.

## Predicted-model confidence

**Request:** “Check what the confidence coloring says about these domains.”

Identify the model source, prediction method and version when recorded, mapped
residues, the actual colored quantity and its legend. Read local confidence and
pairwise uncertainty separately when both are available. A scalar stored in a
B-factor field needs its source meaning established before interpreting it as
pLDDT.

Limit the statement to the available metrics. A domain's local confidence and
the uncertainty in its position relative to another domain answer different
questions. Link the metric file and relevant regions to the statement.

**Useful next step:** confirm the color mapping or attach the PAE data required
for an interdomain-position claim.

## Trajectory event

**Request:** “Check whether this trajectory panel supports a transition.”

Locate topology, trajectory or supplied event analysis, frame-to-time mapping,
the selected interval, stride, replicas and the event definition. Trace the
displayed frames or plot back to that interval and its source. Record which
replicas contribute to an aggregated observation.

Describe a supplied event table at its documented sampling resolution. Record
new occupancy, duration or event measurements after performing that analysis.
Keep the claim's timescale and generality consistent with the sampled evidence.

**Useful next step:** obtain the frame interval or connect the event table and
its analysis settings to the displayed trajectory segment.
