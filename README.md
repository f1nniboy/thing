# thing

## introduction

**thing** is a discord bot that lets you create and manage dynamic plugins called **things** via natural language instructions. an llm writes the plugin code, loads it live, and registers its commands and handlers without requiring a restart.

> **the bot executes arbitrary ai-generated python code on your machine, without any sandboxing. only grant access to people you trust completely**.

## prerequisites

- [uv](https://docs.astral.sh/uv/)
- ollama, local ([ollama.com](https://ollama.com)) or cloud ([ollama.com/cloud](https://ollama.com/cloud))
- discord bot token and application (_[guide](https://discordpy.readthedocs.io/en/stable/discord.html)_)
- discord user IDs of anyone allowed to manage things

## setup

copy `.env.example` to `.env` and fill in the required values:

- `DISCORD_TOKEN` → your bot token
- `OLLAMA_MODEL` → model name (e.g. `gpt-oss:20b`)
- `ALLOWED_USERS` → comma-separated discord user IDs with admin access

optional:

- `OLLAMA_HOST` → ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_API_KEY` → API key for ollama cloud (also enables web agent tools)

take a look at `.env.example` to see all available options.

## running

```console
$ uv run python bot.py
```
