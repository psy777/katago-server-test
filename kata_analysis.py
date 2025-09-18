import subprocess
import json

# Start KataGo
# Use a raw string (r"...") or double backslashes (".\katago") to fix the SyntaxWarning
katago = subprocess.Popen(
    [r"katago", "analysis", "-config", "analysis.cfg", "-model", "default_model.bin"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

# Prepare the corrected request
# The JSON object must be "flat" (no "params" nesting).
# For an empty board, use "initialStones" and "moves".
request = {
    "id": "test1",
    "boardXSize": 19,
    "boardYSize": 19,
    "initialStones": [], # Use initialStones for board setup
    "moves": [],
    "rules": "tromp-taylor", # It's good practice to specify rules
    "analyzeTurns": [0],
    "maxVisits": 100
}


# Send it to KataGo
katago.stdin.write(json.dumps(request) + "\n")
katago.stdin.flush()

# Read response line by line
for line in iter(katago.stdout.readline, ''):
    # Check for an empty line, which indicates the process might have closed stdout
    if not line:
        break
    if '"id":"test1"' in line:
        # Pretty-print the JSON response
        response_json = json.loads(line)
        print("KataGo response:\n", json.dumps(response_json, indent=2))
        break

# Check for any errors on stderr
error_output = katago.stderr.read()
if error_output:
    print("KataGo stderr:\n", error_output)

katago.kill()
