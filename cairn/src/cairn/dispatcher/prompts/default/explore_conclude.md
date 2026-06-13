# Task
You can not and do not execute any command except read.
You will receive a YAML snapshot of the task graph. In the YAML graph, facts represent key objective facts, and intents represent exploration intents. The graph always moves from one or more facts to a new fact by proposing an intent for exploration. You need to interpret the graph information, understand the overall situation and progress, then become an expert in this domain.
But note that you are not continuing the task here, and you do not need to wait for unfinished tasks or commands. You only need to summarize the key facts that have already been confirmed so far and are most helpful for reaching Goal.

# Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

# Rules
- The marked text must contain already confirmed objective factual conclusions. Do not output plans, guesses, or explanatory filler. Do not put long data blobs in the marked text;
- The marked text should contain only the latest incremental facts discovered. Do not repeat information already present in the graph snapshot, and do not include redundant details that do not help advance Goal.
- On success, the output must contain exactly one pair of 32173462130721312360912 markers.

# Context
## Graph
```
{graph_yaml}
```

## Current Intent
```
{intent_id}
```

## Current Intent Description
```
{intent_description}
```
