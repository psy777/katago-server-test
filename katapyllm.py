import subprocess
import json
import argparse
import sys
import os
import logging
from datetime import datetime

# You must install sgfmill: pip install sgfmill
try:
    from sgfmill import sgf, boards
except ImportError:
    print("Error: The 'sgfmill' library is required. Please install it using 'pip install sgfmill'")
    sys.exit(1)

# --- CONFIGURATION ---
KATAGO_COMMAND = [
    "katago", "analysis", "-model", "default_model.bin", "-config", "analysis.cfg"
]
GEMMA_TIMEOUT = 15 # Seconds to wait for Gemma before timing out
LOGS_DIR = "logs"

# Base structure for the KataGo query. Moves and a unique ID will be added to this.
KATAGO_INPUT = {
    "boardXSize": 19,
    "boardYSize": 19,
    "rules": "japanese",
    "komi": 6.5,
    "moves": [],
    "initialStones": [],
    "maxVisits": 5000,
    "includePolicy": True,
    "includeOwnership": True,
}

def parse_sgf_moves(filepath):
    """Parses an SGF file and returns a list of moves in KataGo format."""
    try:
        with open(filepath, "rb") as f:
            game = sgf.Sgf_game.from_bytes(f.read())
    except IOError:
        logging.error(f"Cannot open SGF file at {filepath}")
        return None

    moves = []
    board_size = game.get_size()
    SGF_COLUMNS = "abcdefghijklmnopqrstuvwxyz"
    KATAGO_COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

    try:
        for node in game.get_main_sequence():
            if node.has_property("B"):
                player, move_coords = "B", node.get("B")
            elif node.has_property("W"):
                player, move_coords = "W", node.get("W")
            else:
                continue
            
            if move_coords is None:
                moves.append([player, "pass"])
                continue

            row, col = move_coords
            katago_col = KATAGO_COLUMNS[col]
            katago_row = board_size - row
            moves.append([player, f"{katago_col}{katago_row}"])
    except Exception as e:
        logging.error(f"Error parsing SGF file: {e}")
        return None
        
    return moves

def get_manual_moves():
    """Returns a hard-coded list of moves for analysis if no SGF is provided."""
    return [["B", "Q16"], ["W", "D4"], ["B", "Q4"]]

def run_katago(input_data):
    """Sends a query to the KataGo analysis engine."""
    proc = subprocess.Popen(
        KATAGO_COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True
    )
    input_json = json.dumps(input_data) + "\n"
    stdout_data, stderr_data = proc.communicate(input_json)
    
    lines = stdout_data.strip().split("\n")
    for line in lines:
        if f'"id":"{input_data["id"]}"' in line:
            return json.loads(line)
    
    logging.error(f"No valid KataGo response found.\nSTDOUT: {stdout_data}\nSTDERR: {stderr_data}")
    return None

def format_prompt(kata_output):
    """Formats the data and creates a CONCISE prompt for Gemma."""
    moves = kata_output.get("moveInfos", [])
    if not moves:
        return "The board is empty. In three sentences, describe the most common 3-3 point invasion opening."

    best_move = moves[0]
    prompt = "You are a Go Grandmaster providing a quick, expert opinion.\n\n"
    prompt += "## Analysis Data\n"
    prompt += f"- Current Score: Black leads by {kata_output.get('scoreLead', 0.0):.1f} points.\n"
    prompt += f"- Best Move: {best_move['move']}\n"
    prompt += f"- Winrate after Best Move: {best_move['winrate']*100:.1f}%\n\n"
    prompt += "## Your Task\n"
    prompt += "Based on this data, provide a three-sentence summary for the current player. Explain the most important move and the immediate strategic goal."
    return prompt

def ask_gemma(prompt):
    """Sends the prompt to Gemma via Ollama with a timeout."""
    try:
        result = subprocess.run(
            ['ollama', 'run', 'gemma'],
            input=prompt, capture_output=True, text=True,
            timeout=GEMMA_TIMEOUT, check=False
        )
        return result.stdout
    except subprocess.TimeoutExpired as e:
        logging.warning(f"Gemma timed out after {GEMMA_TIMEOUT} seconds. Returning partial output.")
        return e.stdout if e.stdout else "Gemma timed out and produced no output."

def main():
    # --- 1. Set up Logging and Unique ID ---
    analysis_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file_path = os.path.join(LOGS_DIR, f'{analysis_id}.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file_path),
            logging.StreamHandler(sys.stdout) # To see logs in console too
        ]
    )

    # --- 2. Process Input ---
    parser = argparse.ArgumentParser(description="Analyze a Go position using KataGo and Gemma.")
    parser.add_argument("sgf_file", nargs='?', default=None, help="Optional path to an SGF file to analyze.")
    args = parser.parse_args()

    if args.sgf_file:
        logging.info(f"Loading SGF file: {args.sgf_file}...")
        moves_to_analyze = parse_sgf_moves(args.sgf_file)
        if moves_to_analyze is None:
            sys.exit(1)
    else:
        logging.info("No SGF file provided. Using manual move list from get_manual_moves()...")
        moves_to_analyze = get_manual_moves()
    
    KATAGO_INPUT["id"] = analysis_id
    KATAGO_INPUT["moves"] = moves_to_analyze
    logging.info(f"Analyzing a position with {len(moves_to_analyze)} moves. Analysis ID: {analysis_id}")

    # --- 3. Run KataGo Analysis ---
    logging.info("Running KataGo analysis...")
    kata_result = run_katago(KATAGO_INPUT)
    if kata_result is None:
        logging.error("Exiting due to failed KataGo analysis.")
        sys.exit(1)
        
    logging.info("KataGo analysis successful.")
    # Log the full JSON from KataGo to the file
    logging.getLogger().handlers[0].flush() # Ensure buffer is written
    with open(log_file_path, 'a') as f:
        f.write("\n--- KATA GO ANALYSIS JSON ---\n")
        json.dump(kata_result, f, indent=2)
        f.write("\n---------------------------\n\n")

    # --- 4. Build and Send Prompt to Gemma ---
    logging.info("Building prompt for Gemma...")
    prompt = format_prompt(kata_result)

    # Log the prompt that will be sent
    logging.info(f"--- PROMPT FOR GEMMA ---\n{prompt}\n------------------------")
    
    logging.info(f"Sending to Gemma via Ollama (timeout in {GEMMA_TIMEOUT} seconds)...")
    response = ask_gemma(prompt)
    
    # Log the final response from Gemma
    logging.info(f"--- RESPONSE FROM GEMMA ---\n{response}\n-------------------------")
    
    print("\n🧠 Gemma's concise explanation:\n")
    print(response)

if __name__ == "__main__":
    main()