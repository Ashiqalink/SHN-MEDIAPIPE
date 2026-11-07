# Evaluation and transition contract v1

## Values and expression grammar

Values are booleans, Unicode scalar strings, exact finite decimal numbers, and
an internal `unknown(reason)` sentinel. Unknown is not JSON null, false, or an
exception. Declared but unavailable context values produce unknown in static
mode. In concrete simulation they produce `evaluation.missing_value` and abort
the tick without state or RNG changes. Undeclared names and incorrect types are
L-8 failures in either mode; undeclared flags additionally resolve through L-9
without duplicating L-8 for the same missing flag.

The initial grammar is fixed here; phase 4 implements it and adds the user guide
`docs/expressions.md`. Whitespace is space, tab, CR, or LF. Keywords are lowercase
and bounded by token boundaries. Strings use JSON double-quoted string syntax.

```ebnf
expression = or_expr ;
or_expr    = and_expr, { "or", and_expr } ;
and_expr   = not_expr, { "and", not_expr } ;
not_expr   = "not", not_expr | comparison ;
comparison = atom, [ ("==" | "!=" | "<" | "<=" | ">" | ">="), atom ] ;
atom       = number | string | "true" | "false"
           | property | flag_read | random_call | "(", expression, ")" ;
property   = identifier, { ".", identifier } ;
flag_read  = "flag", "[", string, "]" ;
random_call = "random", "(", number, ")" ;
identifier = lowercase_or_underscore, { lowercase_or_digit_or_underscore } ;
number     = ["-"], ("0" | nonzero_digit, {digit}),
             [".", digit, {digit}], [("e" | "E"), ["+" | "-"], digit, {digit}] ;
```

`random` and `flag` are reserved; properties must match declared context paths.
`random(p)` accepts a numeric literal in [0, 1], not an expression or variable.
The expression as a whole must have boolean type. Equality requires the same
type; ordered comparisons require numbers. Strings compare only for equality,
by decoded scalar sequence with no Unicode normalization. Booleans are not
integers. No null literals, arithmetic, assignments, indexing other than flag
reads, chained comparisons, imports, methods, interpolation, or additional
functions. Validate the whole AST before evaluation, including unreachable RHS
branches; short circuiting cannot hide unsafe syntax or unknown names.

Numbers are `(integer coefficient, decimal exponent)` with exact comparisons.
`1`, `1.0`, and `1e0` compare equal; negative zero compares equal to zero while
its source spelling survives no-op saves. No float conversion is permitted.
JSON `integer` means mathematically integral (so `1.0` satisfies integer);
boolean never satisfies number/integer. No arithmetic operators are in v1.
Resource limits are 4,096 UTF-8 bytes per expression, 128 nested AST levels,
1,024 coefficient digits per numeric token, and absolute decimal exponent at
most 6,144 after parsing. Numeric limits also apply to content. Violations are
explicit `expression.limit` or `content.number_limit` errors, never truncation.

Evaluate left to right. Concrete `and`/`or` short circuit. In static mode use:

| Left | Operator | Right evaluated? | Result |
|---|---|---|---|
| false | and | no | false |
| true | and | yes | right |
| true | or | no | true |
| false | or | yes | right |
| unknown | and | yes | false if right is false, otherwise unknown |
| unknown | or | yes | true if right is true, otherwise unknown |

`not unknown` is unknown; a comparison involving unknown is unknown. Merge
multiple unknown reasons as a sorted unique list. Static `random(0)` is false,
`random(1)` is true, and `random(p)` for 0 < p < 1 is unknown(`probabilistic`).
Static evaluation consumes **zero** RNG draws, including endpoint calls.

## Portable randomness

Algorithm name is `pcg32-xsh-rr-v1`. All shifts are logical. `mask64 = 2^64 - 1`,
`mask32 = 2^32 - 1`. The following is mathematical pseudocode, not host-language
integer behavior:

```text
draw():
    old = state
    state = (old * 6364136223846793005 + increment) & mask64
    x = (((old >> 18) xor old) >> 27) & mask32
    rotation = old >> 59
    return ((x >> rotation) | (x << ((-rotation) & 31))) & mask32

initialize(seed, stream):
    state = 0
    increment = ((stream << 1) | 1) & mask64
    draw()                         # discarded initialization draw
    state = (state + seed) & mask64
    draw()                         # discarded initialization draw
```

This specifies the [PCG author's reference algorithm](https://github.com/imneme/pcg-c-basic/blob/master/pcg_basic.c).
Do not substitute a different PCG output variant. Seed is an unsigned 64-bit
integer; stream is an unsigned 63-bit integer (reject higher values instead of
aliasing streams). Reports/fixtures encode seed, stream, state, and increment as
canonical decimal **strings** to preserve precision in JavaScript. No seed from
clock, PID, address, hash-map order, or host random module is permitted.

For a concrete call `random(p)`, consume exactly one `draw()` when the AST node
is reached, even if p is 0 or 1. Return `u < floor(p * 2^32)` using exact decimal
arithmetic and an integer threshold. Thus p=1 always succeeds and p=0 never
succeeds. Skipped short-circuit branches consume no draw. Nonendpoint
probabilities have a 2^-32 sampling resolution; never compare a host float to p.

For seed `42`, stream `54`, the first six draws are `a15c02b7`, `7b47f409`,
`ba1d3330`, `83d2f293`, `bfa4784b`, `cbed606e`, as in the
[published PCG demo](https://www.pcg-random.org/using-pcg-c-basic.html).
The fixture includes these hexadecimal words and exact post-initialization and
post-draw states. Leading zeros in words are required; state uses decimal strings.

A scenario owns one RNG stream. Each branch snapshots state, increment, tick,
and all content state, then proceeds without reseeding. Two identical branch
snapshots and choices produce byte-identical reports. A failed tick rolls back
RNG as well as content. A valid tick with no selected transition still commits
draws consumed while testing candidate guards.

## Shared transition kernel (FR-25)

The shared pure interfaces are conceptually:

```text
compile(project) -> ordered transition definitions or diagnostics
enabled(transition, state, mode, rng?) -> true | false | unknown | error
apply(transition, state) -> new state + ordered changes
successors(state, mode, rng?) -> next state(s) + evaluations + rng?
```

This is one implementation path with explicit mode, not two independently
implemented evaluators. Kernel input, output, and unknowns are data, never UI
callbacks. Compilation resolves schema roles/references into the same definitions
for lint and simulation. Neither caller may invent edges by ignoring guards,
input multiplicity, exit conditions, or flag writes.

V1 reaction state is a finite material multiset with nonnegative integer counts,
boolean flags, quest-stage IDs, and declared expression context. This is an
authoring evaluator, not a spatial falling-sand runtime. A reaction's ordered
inputs consume one unit per entry (duplicates require multiple units); outputs
produce one unit per entry. Its first input is the subject material. Subject
properties come from that material's declared properties, overlaid only by
explicit scenario subject bindings. Neighbor properties are supplied explicitly
by a scenario; no geometry or neighborhood selection is guessed. State/subject/
neighbor property bindings follow the schema context declarations.

Reaction eligibility requires sufficient counts, true `condition` (default true),
and false `exitCondition` (default false). A declared exitCondition is a stopping
guard: once true, that reaction cannot fire. Apply consumption and production
atomically. Spawn rules initialize available materials once, in category/source
order, one unit per eligible nonzero-weight rule; weight is eligibility metadata
in v1, not an implicit random choice. Scenarios may instead supply explicit
starting counts. No implicit spawning occurs on later ticks.

Quest transitions require the current stage, quest required flags all true, and
a true condition (default true). Apply target stage and all declared flag writes
atomically. Conflicting writes to one flag in a transition are invalid content.
Terminal stages have no outgoing transitions; violation is a structural error.
Quest-only graphs are supported with an empty material multiset. State snapshots
include flags and stages, so reachability does not assume incompatible flag paths
can coexist. Declared initial flag values seed static exploration unless game
code can write them (`external_writes`); those flags are abstract unknowns until
a modeled action establishes a value. Scenarios provide concrete values for them.

Each tick selects at most **one** transition globally. Candidate order is ascending
integer priority (default 0), category name, owning quest ID (empty for reactions),
source stage ID (empty for reactions), then reaction ID or transition array index.
String comparisons use Unicode scalar order; array indices compare numerically.
Read all guards against the tick's original content snapshot. Test candidates in
order; stop at the first eligible transition. Lower priority candidates consume
no draws once one is selected. Its effects become visible on the next tick.
Record rejected evaluated candidates, chosen transition or null, ordered changes,
and RNG before/after. No candidate means an idle tick. Batch scenarios explicitly
declare their tick count; no wall-clock stopping rules.

Static exploration follows this same priority selection: false skips; true
selects and stops; unknown forks into a selected branch and a fall-through branch.
Unknown branches carry their reason and may not be reported as proven reachable.
An abstract context value remains unknown on later ticks unless a modeled action
sets it; do not infer correlations between unknown values. Known reachable
materials pass L-6; absent materials fail only after exhaustive exploration with
no unknown path to them. `spawn_external` or a potentially producing unknown path
makes the corresponding absence unknown. Exploration uses full modeled state
(including counts, flags, and stages), memoizes equivalent states, and has a
10,000-state limit per query. Any unexplored potentially relevant branch yields
unknown(`analysis_limit`), never a claim of unreachable. An individual negative
result must have an exhausted proof, not merely an unvisited graph node.

## Reaction-cycle meaning and quest sample

L-7 builds material/reaction strongly connected components using compiled
transition definitions. A component is cyclic if it has >1 material vertex or
a self-loop. Statically false reactions are omitted. A cyclic component without
a declared usable exit emits a warning. A declared exitCondition proven true
disables its reaction before graph construction. A declared false exit does not
resolve a cycle. A runtime-dependent exit or ordinary cycle guard makes the
result unknown when it could determine the cycle's presence or termination.
A constant true outgoing reaction that leads outside the component counts as
a declared exit only if the shared kernel's priority and counts analysis proves
it is selectable from every reachable cycle state. If it cannot prove that,
the result is unknown, not a clean pass. A graph edge alone is not proof of exit.

The quest sample in phase 5 must include material transitions `dormant -> awake`
and `awake -> dormant`. No exit: L-7 fail. `flag["release"]` as a stopping guard
with `release` declared externally written and no modeled assignment: L-7 unknown.
A statically true stopping guard
removes one edge: no L-7 diagnostic. Quest stage loops do not trigger L-7 and
remain legal when all nonterminal stages have outgoing transitions. This resolves
the apparent PRD Section 10 mismatch without redefining L-7 as quest-loop lint.
