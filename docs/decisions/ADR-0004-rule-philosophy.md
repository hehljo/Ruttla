# ADR-0004 — Evidence-Backed Deterministic Rules

## Status
Proposed

## Context
Public growth can dilute the current high-value pattern if contributors add speculative style regexes.

## Decision
Official rules require real/minimal failure evidence, healthy counterexample, public rationale and false-positive analysis.

## Alternatives
- accept broad best-practice rules by default
- become an aggregator of existing linters

## Why
Trust in the gate depends more on precision and evidence than raw rule count.

## Consequences
Rule growth is slower but higher quality. Existing linters are referenced/integrated rather than reimplemented where they already solve the problem.

## Validation
Contribution template and CI metadata checks enforce required evidence.
