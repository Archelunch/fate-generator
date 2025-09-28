# Fate Generator

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Poetry](https://img.shields.io/badge/poetry-1.8.2+-blue.svg)](https://python-poetry.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-orange?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/maktail)

> An Tool to quickly generate characters for the Fate Core tabletop RPG powered by [DSPy](https://dspy.ai).

## Table of Contents

- [Fate Generator](#fate-generator)
  - [Table of Contents](#table-of-contents)
  - [Features](#features)
  - [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
      - [Local Development](#local-development)
  - [Usage](#usage)
  - [Configuration](#configuration)
    - [Required Keys](#required-keys)
    - [Key Configuration Options](#key-configuration-options)
    - [Using Other Model Providers](#using-other-model-providers)
  - [Training, Datasets, and Validation](#training-datasets-and-validation)
    - [Directory layout](#directory-layout)
    - [Environment and configuration](#environment-and-configuration)
    - [1) Dataset generation](#1-dataset-generation)
    - [2) Training (GEPA optimization)](#2-training-gepa-optimization)
    - [3) Validation and comparison](#3-validation-and-comparison)
  - [Attribution](#attribution)

## Features

-   **Character Idea Generation**: Quickly spin up a character concept from a simple idea.
-   **Interactive UI**: Drag-and-drop skills, add/regenerate aspects and stunts, and manage your character sheet dynamically.
-   **DSPy-Powered**: Uses `dspy` to generate datasets and optimize prompts for high-quality, structured LLM outputs.

## Getting Started

### Prerequisites

-   Python 3.12+
-   [Poetry](https://python-poetry.org/docs/#installation) for dependency management.
-   An API key for a Gemini model or other providers (see [Configuration](#configuration)).

#### Local Development

1.  **Install dependencies:**
    ```bash
    make install
    ```
    Alternatively, if you don't have `make`:
    ```bash
    poetry install
    ```

2.  **Run the application:**
    ```bash
    make run
    ```
    This will start a development server at `http://localhost:8000`.

## Usage

Enter a character idea (e.g., "Witty detective with a dark past") and an optional setting description, then click "Generate Character".

The user interface allows you to:
-   Drag and drop skills to rearrange the pyramid.
-   Regenerate individual aspects.
-   Add new aspects and stunts.
-   Customize the list of available skills for your game.
-   View previously generated ideas in the History panel.

## Configuration

The application is configured through environment variables and a YAML file.

-   `app/config/settings.py` defines the available settings using Pydantic.
-   `app/config/app.yaml` provides default values.
-   Environment variables can be used to override any setting.

A `.env` file can be used for local development to set environment variables.

An example `app/config/app.yaml` might look like this:

```yaml
app_name: Fate Generator
environment: dev
log_level: INFO

# Artifacts (can be absolute or relative to project root)
artifact_skeleton_path: artifacts/gepa_character_skeleton.json
artifact_remaining_path: artifacts/gepa_remaining.json
artifact_gm_hints_path: artifacts/gepa_gm_hints.json

# DSPy / LLM
dspy_model: gemini/gemini-2.5-flash-lite
dspy_temperature: 0.7
dspy_max_tokens: 20000
dspy_cache: false

dspy_reflection_model: gemini/gemini-2.5-pro
```

### Required Keys

The application uses a Gemini model via `dspy` by default. You need to provide an API key. The application will look for the key in the following environment variables, in order:
-   `DSPY_API_KEY` # any other models
-   `GEMINI_API_KEY`
-   `GOOGLE_API_KEY`

### Key Configuration Options

-   `DSPY_MODEL`: The main language model to use (e.g., `gemini/gemini-2.5-flash-lite`).
-   `DSPY_REFLECTION_MODEL`: The model used for optimization/reflection (e.g., `gemini/gemini-2.5-pro`).
-   `LOG_LEVEL`: Set the application's log level (e.g., `INFO`, `DEBUG`).

### Using Other Model Providers

This project is built on `dspy`, which supports various language model providers (e.g., OpenAI, Cohere, Hugging Face). To use a different provider, you will need to update the `dspy_model` and `dspy_reflection_model` settings and provide the appropriate API key as an environment variable.

For example, to use OpenAI's GPT-4, you might set the following in your `.env` file or `app.yaml`:

```yaml
# In .env
OPENAI_API_KEY="your-openai-api-key"

# In app.yaml
dspy_model: "openai/gpt-4o"
dspy_reflection_model: "openai/gpt-4-turbo"
```

Refer to the [DSPy documentation](https://dspy.ai/learn/programming/language_models/) for a full list of supported models and their required configuration.

## Training, Datasets, and Validation

This project includes a full workflow to generate datasets, train optimized DSPy programs (GEPA), and validate performance against baselines.

### Directory layout

- `datasets/`: JSON datasets used for training/validation (`dataset_*.json`, plus seed `ideas.json`).
- `artifacts/`: Saved optimized DSPy program checkpoints (`gepa_*.json`).
- `scripts/`: CLI utilities for dataset generation, training, and validation.

### Environment and configuration

- Configure models and API keys via environment or `app/config/app.yaml`.
- API key lookup order for Gemini-compatible providers: `DSPY_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`.
- Important settings (see `app/config/settings.py`):
  - `dspy_model` (default: `gemini/gemini-2.5-flash-lite`)
  - `dspy_reflection_model` (default: `gemini/gemini-2.5-pro`)
  - `dspy_temperature`, `dspy_max_tokens`, `dspy_cache`
  - `artifact_*_path` and directories resolved under `artifacts/` and `datasets/`

### 1) Dataset generation

Datasets are produced in three stages using `scripts/generate_dataset.py`.

Seed ideas live in `datasets/ideas.json` (array of objects: `{ "idea": str, "setting"?: str | null }`).

1. Skeletons (initial character sheet pieces)

```bash
poetry run python scripts/generate_dataset.py skeleton datasets/ideas.json
# -> writes datasets/dataset_skeleton.json
```

2. Remaining suggestions (aspects & stunts)

```bash
poetry run python scripts/generate_dataset.py remaining datasets/dataset_skeleton.json
# -> writes datasets/dataset_remaining.json
```

3. GM hints

```bash
poetry run python scripts/generate_dataset.py hints datasets/dataset_remaining.json
# -> writes datasets/dataset_gm_hints.json
```

Notes:
- Each stage validates inputs and reports progress.
- Output structure is tailored for the corresponding train/validate scripts.

### 2) Training (GEPA optimization)

Each task has a dedicated training script that loads its dataset, splits train/val, compiles an optimized DSPy program with GEPA, and saves the checkpoint into `artifacts/`.

- Character Skeleton

```bash
poetry run python scripts/train_gepa_skeleton.py
# saves artifacts/gepa_character_skeleton.json
```

- Remaining Suggestions (Aspects/Stunts)

```bash
poetry run python scripts/train_gepa_remaining.py
# saves artifacts/gepa_remaining.json
```

- GM Hints

```bash
poetry run python scripts/train_gepa_gm_hints.py
# saves artifacts/gepa_gm_hints.json
```

All training scripts use the same settings (model, reflection model, temperature, tokens) via `app/config/app.yaml` and environment variables.

### 3) Validation and comparison

Use `scripts/validate_performance.py` to compare baseline vs optimized programs with rich tables and per-example panels. Defaults read datasets from `datasets/` and checkpoints from `artifacts/` (configurable via flags).

Examples:

```bash
# Validate both skeleton and remaining using defaults
poetry run python scripts/validate_performance.py --task both --threads 4

# Validate only skeleton with a quick subset
poetry run python scripts/validate_performance.py --task skeleton --limit 50

# Validate with custom checkpoint paths
poetry run python scripts/validate_performance.py \
  --skeleton-checkpoint artifacts/gepa_character_skeleton.json \
  --remaining-checkpoint artifacts/gepa_remaining.json
```

Supported tasks: `skeleton`, `remaining`, `gm_hints`, `both`, `all`.

## Attribution

This work is based on Fate Core System and Fate Accelerated Edition (found at fate-srd.com), products of Evil Hat Productions, LLC, developed, authored, and edited by Leonard Balsera, Brian Engard, Jeremy Keller, Ryan Macklin, Mike Olson, Clark Valentine, Amanda Valentine, Fred Hicks, and Rob Donoghue, and licensed for our use under the Creative Commons Attribution 3.0 Unported license (CC BY 3.0).
