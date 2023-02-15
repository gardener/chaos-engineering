# **Module: `human`**

## Purpose

### What?

This module provides [`chaostoolkit`](https://chaostoolkit.org) actions for human interaction. It supports:

- **Wait-For**: Wait for human user to either press `Enter` to continue or `CTRL-C` to abort.

### How?

- **Wait-For**: Wait for keyboard input.

### Why?

This is useful in combination with `assess_filters_impact` from the other modules as a way of "dry-run", see example.

## Usage

### Actions and Rollbacks

`chaostoolkit` introduces so-called [actions](https://chaostoolkit.org/reference/api/experiment/#action) that can be composed into [experiments](https://chaostoolkit.org/reference/api/experiment/#experiment) that perform operations against a system (here a human). The following actions are supported:

Module: [`chaosgarden.human.actions`](/chaosgarden/human/actions.py)

- `wait_for`: Wait for human user to either press `Enter` to continue or `CTRL-C` to abort.

### Configuration

No [configuration](https://chaostoolkit.org/reference/api/experiment/#configuration) required.

### Secrets

No [secrets](https://chaostoolkit.org/reference/api/experiment/#secrets) required.

## Examples

- [Wait-For](/docs/human/wait-for.json)
