# Local setup (macOS)

How to get Slotline onto your Mac and work on it with Claude Code locally. You can mix this
with cloud sessions on claude.ai/code: both work on the same GitHub branches.

| Use | When |
| --- | --- |
| **Cloud session** (claude.ai/code) | Building a session's PR; runs while your laptop is closed; Docker ready |
| **Local Claude Code** (`claude` in Terminal) | Reviewing and running code yourself, debugging, learning by stepping through it |

---

## 1. Install the tools (once, ~20 min)

```bash
# Homebrew (skip if `brew --version` works)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# git, GitHub CLI, make
brew install git gh make

# uv: Python package manager; it also installs Python 3.13 for the project
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker Desktop: runs Postgres, Redis, Mailpit
brew install --cask docker        # then open Docker.app once and let it start

# Claude Code (native installer, auto-updates)
curl -fsSL https://claude.ai/install.sh | bash
```

Open a **new** Terminal window, then check everything:

```bash
git --version && gh --version && uv --version && docker --version && claude --version
```

Log in to GitHub once:

```bash
gh auth login          # choose GitHub.com → HTTPS → login with browser
```

## 2. Clone the repo

```bash
mkdir -p ~/code && cd ~/code
gh repo clone kartik8904/slotline
cd slotline
git fetch --all
git switch dev         # always work from dev, never main
```

## 3. Start Claude Code in the repo

```bash
cd ~/code/slotline
claude                 # first run opens the browser to log in with your claude.ai account
```

Claude reads `CLAUDE.md` automatically. Good first message:

```text
Read CLAUDE.md, docs/PROJECT-OVERVIEW.md and docs/architecture.md. Don't change anything.
Explain Slotline to me in 10 bullets and tell me which session we're on from docs/progress.md.
```

The SessionStart hook in `.claude/settings.json` does nothing on your laptop (it only runs in
cloud sessions), so start the services yourself once the project exists (after session 1):

```bash
uv sync                                        # install Python deps
docker compose up -d postgres redis mailpit    # start services
make test                                      # run tests
make dev                                       # API at http://localhost:8000/docs
```

Mailpit's inbox (to see emails the app sends) is at http://localhost:8025.

## 4. Pick up a cloud session's branch locally

After a cloud session opens a PR, check its code out to run and read it yourself:

```bash
git fetch
git switch feature/s01-skeleton
uv sync && make test && make dev
```

Or pull the whole cloud session (conversation + branch) into your terminal:

```bash
claude --teleport      # pick the session from the list
```

Start a cloud session from your terminal (uses the branch you're on, so push first):

```bash
claude --cloud "Read CLAUDE.md and docs/session-prompts.md, then run the Session 1 prompt"
```

## 5. Daily commands

```bash
git switch dev && git pull                 # start of day
git switch -c feature/sNN-name             # new work (Claude does this in cloud sessions)
make lint && make test                     # before every push
git push -u origin HEAD
gh pr create --base dev --fill             # PR into dev
gh pr checks                               # watch CI
docker compose down                        # end of day (keeps data)
docker compose down -v                     # wipe the local database
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `claude: command not found` | Open a new Terminal window; else see the install troubleshooting docs |
| `Cannot connect to the Docker daemon` | Open Docker.app and wait for it to say "running" |
| Port 5432 already in use | You have a local Postgres running: `brew services stop postgresql` |
| `uv sync` fails on Python version | `uv python install 3.13` |
| Tests can't reach the database | `docker compose ps`; restart with `docker compose up -d postgres` |

Reference: [Claude Code setup](https://code.claude.com/docs/en/setup),
[cloud sessions and teleport](https://code.claude.com/docs/en/claude-code-on-the-web).
