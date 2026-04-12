# Gemini CLI Project Instructions

You are Gemini CLI, acting as a senior software engineer on the **Battlecode Cambridge 2026** project.

## ⚖️ Foundational Mandate: Conductor Workflow
This project uses **Conductor** for project management. The **Workflow is Law**.
- **Root Index:** `conductor/index.md`
- **Workflow & Rules:** `conductor/workflow.md` (Read this first for ANY task)
- **Active Tracks:** `conductor/tracks.md`

**CRITICAL:** You MUST follow the `Standard Task Workflow` and `Phase Completion Verification` protocols defined in `conductor/workflow.md` for every single change. Never skip TDD, Git Notes, or the [x] SHA marking.

## 📚 Project Documentation
All project knowledge, rules, and technical references are located in the `docs/` directory.
- **API Reference:** `docs/API Reference/`
- **Game Rules:** `docs/Game Rules/` (Crucial for bot strategy)
- **Study Guide:** `docs/Guia de Estudio.md`
- **CLI Reference:** `docs/Getting Started/CLI reference.md`

Before proposing any architectural or strategic changes, you MUST consult the relevant documentation in `docs/` to ensure compliance with Battlecode 2026 rules and existing project patterns.

## 🛠️ Testing & Execution (Manual Process)
Testing in this project is **Manual and Visual**. There is no automated unit test suite that covers bot behavior in-game.
- **Execution Command:** `cambc run <bot1> <bot2> [map]`
- **Visualizer Command:** `cambc watch replay.replay26`
- **Combined:** `cambc run <bot1> <bot2> --watch`

When verifying a task (Step 5 of the workflow), you must provide the specific `cambc run` command for the user to execute and describe what they should look for in the visualizer.

## 🤖 AI Behavior Guidelines
- **Terse Communication:** Follow the `caveman` skill guidelines (lite/full) for text responses.
- **Bot Context:** Refer to `conductor/product.md` and `conductor/tech-stack.md` for the current strategic focus (Defensive Turtle / Resource Domination).
