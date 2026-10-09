# My agent profile

What is mine on top of the public `.agents` at `~/.agents`. Keep this repo private.

| | |
|---|---|
| `standards/*.md` | your standards. One named like a starter replaces it; any other is added |
| `agents/*.md` | reviewer definitions, the same way |
| `config.toml` | `[review]`, `[inject]`, `[guard]` and `[backends]` settings over the ones in `.agents`, under this machine's `local.toml`; a backend here replaces the one of the same name |
| `AGENTS.md` | how you work, loaded into every session after the one in `.agents` |

On a new machine:

```sh
git clone https://github.com/<you>/.agents ~/.agents
~/.agents/bin/agent install --profile git@github.com:<you>/.agents.profile.git
```

`agent update` pulls both, and `agent doctor` says when this repo has work that is not pushed.
