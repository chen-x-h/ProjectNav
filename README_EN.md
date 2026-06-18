# Project Nav

A web-based project manager built with NiceGUI for managing local web services — start, stop, and monitor their status.

![Overview](imgs/overview.png)

## Features

- **Project CRUD** — Add, edit, delete projects with name, description (Markdown), URL, category, start/stop script paths
- **Health Check** — Check project URL reachability, green/red/gray dot status indicator
- **Script Execution** — One-click start/stop scripts, auto-start on boot + batch mode
- **Extra Links** — Attach multiple extra links per project
- **Filter & Search** — Search by name, filter by category, show auto-start only
- **Category Grouping** — Projects grouped by category
- **Script Templates** — View start/stop script templates from the edit dialog

## Quick Start

```bash
pip install nicegui httpx
python main.py
```

Visit http://localhost:20001

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Listen address |
| `PORT` | `20001` | Listen port |
| `PROJECTS_FILE` | `./projects.json` | Project data file path |
| `LOG_FILE` | system temp dir | Log file path |
| `START_TEMPLATE` | `./start_script_template.txt` | Start script template file |
| `STOP_TEMPLATE` | `./stop_script_template.txt` | Stop script template file |

## Docker Deployment

```bash
cd docker
mkdir data
docker compose up -d
```

- **Host Network** — Uses `network_mode: host`; container's `localhost` is the host's `localhost`
- **Change Port** — Via `PORT` env var: `PORT=3000 docker compose up -d`
- **Persistence** — Data, logs, templates stored in `docker/data/`
- **Mirror** — Built-in Aliyun PyPI mirror
- **Timezone** — Default `Asia/Shanghai`

### Build Manually

```bash
docker compose build --no-cache
docker compose up -d
```

## Start / Stop Script Reference

Start/stop scripts are executed directly via `subprocess`. It is recommended to use `tmux` or `screen` for process isolation.

### Start Script Example (tmux)

```bash
#!/bin/bash

LOG="/path/to/your_project/log.out"
SESSION_NAME="my_project"

echo "[$(date)] Starting service..." >> "$LOG"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME"
fi

tmux new-session -d -s "$SESSION_NAME"
tmux send-keys -t "$SESSION_NAME" 'cd /path/to/your_project' C-m
tmux send-keys -t "$SESSION_NAME" './start_service.sh' C-m
tmux detach-client -t "$SESSION_NAME"
echo "[$(date)] Service started." >> "$LOG"
```

### Stop Script Example (tmux)

```bash
#!/bin/bash

SESSION_NAME="my_project"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME"
fi
```

### Template File Layout

```
project_root/
├── main.py
├── start_script_template.txt
├── stop_script_template.txt
├── projects.json
├── imgs/
│   └── overview.png
└── docker/
```

## Acknowledgements

Thanks to [opencode](https://opencode.ai) for the AI-assisted development.
