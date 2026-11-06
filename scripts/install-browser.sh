#!/usr/bin/env bash
# Explicit, user-local installation. No sudo, no user-browser attachment.
set -euo pipefail
backend_dir="${XDG_DATA_HOME:-$HOME/.local/share}/omnimcp/backends/playwright"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omnimcp"
if [[ -e "$config_dir/browser.json" ]]; then
    echo "Existing browser.json retained. Inspect it before installing a different backend." >&2
    exit 1
fi
npm install --prefix "$backend_dir" --save-exact @playwright/mcp@0.0.83
"$backend_dir/node_modules/.bin/playwright" install chromium --no-shell
mkdir -p "$config_dir"
python3 - "$backend_dir" "$config_dir/browser.json" <<'PY'
import json, os, pathlib, subprocess, sys
backend=pathlib.Path(sys.argv[1])
executable=subprocess.check_output(['node','-e',"console.log(require('playwright').chromium.executablePath())"],cwd=backend,text=True).strip()
state=pathlib.Path(os.environ.get('XDG_STATE_HOME',str(pathlib.Path.home()/'.local/state')))/'omnimcp'
command=[str(backend/'node_modules/.bin/playwright-mcp'),'--headless','--executable-path',executable,
         '--user-data-dir',str(state/'browser-profile'),'--output-dir',str(state/'browser-output')]
path=pathlib.Path(sys.argv[2])
with path.open('x') as stream:
    json.dump({'backend':'@playwright/mcp','version':'0.0.83','command':command},stream,indent=2)
path.chmod(0o600)
print(path)
PY
