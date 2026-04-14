# AI/ML in Particle Therapy Repository Catalog

This repository automatically discovers, classifies, and publishes repositories that sit at the intersection of:

- particle therapy, proton therapy, ion beam therapy, hadron therapy
- machine learning, deep learning, AI, neural networks

## What this repo does

- searches GitHub and GitLab
- collects repository metadata and README evidence
- filters candidates with domain heuristics
- classifies repositories with an LLM
- publishes a searchable static catalog via GitHub Pages

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN=...
export GITLAB_TOKEN=...
export OPENAI_API_KEY=...
python run.py
