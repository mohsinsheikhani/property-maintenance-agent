# Cost Optimization Sequencing

Optimize in strict order: Quality -> Latency -> Cost. Never reverse.

---

## Why This Order

| Sequence | Result |
|----------|--------|
| Quality -> Latency -> Cost | Ship working, fast, cheap agent |
| Quality -> Cost -> Latency | Ship working, cheap, slow agent (users complain) |
| Latency -> Quality -> Cost | Ship fast, expensive, broken agent |
| Cost -> Quality -> Latency | Ship cheap, broken, slow agent (worst) |

---

## Phase 1: Quality (Achieve threshold regardless of cost/latency)

Use the most capable model (e.g., claude-opus-4) to establish quality ceiling.

```python
def phase_1_quality(self):
    """Achieve quality threshold (>=90%) regardless of cost/latency."""
    # Using most capable, expensive, slow model
    while self.eval_score < 0.90:
        self.iterate_on_quality()
    self.proceed_to_phase_2()
```

## Phase 2: Latency (Reduce while maintaining quality threshold)

```python
def phase_2_latency(self):
    """Reduce latency while maintaining quality threshold."""
    optimizations = [
        ("Reduce prompt length", self.try_shorter_prompt),
        ("Parallel tool calls", self.enable_parallel_tools),
        ("Cache common contexts", self.add_prompt_caching),
        ("Streaming responses", self.enable_streaming)
    ]

    for name, optimization in optimizations:
        optimization()
        new_score = self.run_evals()
        if new_score < 0.90:
            self.revert()  # Quality regression - revert
            continue
        # Measure latency improvement and keep
```

## Phase 3: Cost (Reduce while maintaining quality + latency)

```python
def phase_3_cost(self):
    """Reduce cost while maintaining quality + latency thresholds."""
    optimizations = [
        ("Switch to Sonnet (from Opus)", self.try_smaller_model),
        ("Switch to Haiku (from Sonnet)", self.try_smallest_model),
        ("Reduce context window", self.optimize_context),
        ("Cache embeddings", self.add_embedding_cache)
    ]

    for name, optimization in optimizations:
        optimization()
        new_score = self.run_evals()
        if new_score < 0.90:
            self.revert()  # Quality regression
            continue
        new_latency = measure_p95_latency()
        if new_latency > self.latency_threshold:
            self.revert()  # Latency regression
            continue
        # Measure cost improvement and keep
```

---

## Anti-Pattern

```python
# WRONG: Optimizing cost before quality
agent = Agent(model="haiku")  # Cheap model first
# Now struggling to reach quality threshold with limited model

# CORRECT: Achieve quality first
agent = Agent(model="opus")  # Most capable model
# Iterate until quality threshold met
# Then swap to cheaper model, verify quality maintained
# If quality drops, stay with opus
```

Quality gates can't be satisfied with capability-limited models. Starting with the most capable model establishes the quality ceiling. Then systematically trade capability for speed/cost while maintaining quality threshold. Reversing this order wastes effort trying to engineer around fundamental capability gaps.
