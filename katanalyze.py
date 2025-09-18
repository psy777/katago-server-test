# katanalyze.py (with coordinate system fix)

import json
import argparse
import sys
import os
import logging
from datetime import datetime

# You must install sgfmill and requests:
# pip install sgfmill requests
try:
    from sgfmill import sgf
except ImportError:
    print("Error: The 'sgfmill' library is required. Please install it using 'pip install sgfmill'")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Error: The 'requests' library is required. Please install it using 'pip install requests'")
    sys.exit(1)


# --- CONFIGURATION (Defaults and constants) ---
# The katago_api.py server must be running and accessible at this URL.
KATAGO_API_URL = "http://localhost:8000/analyze"
API_TIMEOUT = 180  # Max time to wait for a response from the API
LLM_TIMEOUT = 60
LOGS_DIR = "logs"
KATAGO_COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"


# --- SCRIPT LOGIC ---

def parse_sgf_file(filepath):
    """
    Parses an SGF file, extracting board size, initial stones, all moves, and initial player.
    """
    try:
        with open(filepath, "rb") as f:
            game = sgf.Sgf_game.from_bytes(f.read())
        board_size = game.get_size()
    except Exception as e:
        logging.error(f"Cannot open or parse SGF file at {filepath}: {e}")
        return None, None, None, None

    root_node = game.get_root()

    # Correctly determine the initial player for handicap games.
    initial_player = "B"
    if root_node.has_property('PL'):
        player_prop = root_node.get('PL').upper()
        if player_prop in ['B', 'W']:
            initial_player = player_prop
    elif root_node.has_property('AB'):
        initial_player = "W"

    initial_stones = []
    if root_node.has_property('AB') or root_node.has_property('AW'):
        (black_stones, white_stones, _) = root_node.get_setup_stones()
        for row, col in black_stones:
            katago_col = KATAGO_COLUMNS[col]
            # --- COORDINATE FIX ---
            # Changed from 'board_size - row' to 'row + 1' to use top-down indexing.
            katago_row = row + 1
            initial_stones.append(["B", f"{katago_col}{katago_row}"])
        for row, col in white_stones:
            katago_col = KATAGO_COLUMNS[col]
            # --- COORDINATE FIX ---
            # Changed from 'board_size - row' to 'row + 1' to use top-down indexing.
            katago_row = row + 1
            initial_stones.append(["W", f"{katago_col}{katago_row}"])

    moves = []
    try:
        for node in game.get_main_sequence():
            prop, move_coords = "", None
            if node.has_property("B"):
                prop, move_coords = "B", node.get("B")
            elif node.has_property("W"):
                prop, move_coords = "W", node.get("W")
            else:
                continue

            if move_coords is None:
                moves.append([prop, "pass"])
                continue

            row, col = move_coords
            katago_col = KATAGO_COLUMNS[col]
            # --- COORDINATE FIX ---
            # Changed from 'board_size - row' to 'row + 1' to use top-down indexing.
            katago_row = row + 1
            moves.append([prop, f"{katago_col}{katago_row}"])
    except Exception as e:
        logging.error(f"Error parsing SGF move sequence: {e}")
        return None, None, None, None

    return board_size, initial_stones, moves, initial_player


def request_katago_analysis_from_api(board_size, initial_stones, moves, initial_player, max_visits, turn_to_analyze):
    """
    Sends an analysis query to the KataGo API for a specific turn and returns the JSON response.
    """
    katago_query = {
        "boardXSize": board_size,
        "boardYSize": board_size,
        "initialStones": initial_stones,
        "moves": moves,
        "rules": "japanese",
        "initialPlayer": initial_player.lower(),
        "maxVisits": max_visits,
        "analyzeTurns": [turn_to_analyze],
    }

    logging.info(f"Sending query to KataGo API at {KATAGO_API_URL}")
    logging.debug(f"Constructed API Query: {json.dumps(katago_query)}")

    try:
        response = requests.post(
            KATAGO_API_URL,
            json=katago_query,
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        logging.info("Full analysis received from KataGo API.")
        return response.json()
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection Error: Could not connect to the KataGo API at {KATAGO_API_URL}.")
        logging.error("Please ensure the katago_api.py server is running and accessible.")
        return None
    except requests.exceptions.Timeout:
        logging.error(f"Request timed out after {API_TIMEOUT} seconds. The KataGo engine may be overloaded or stuck.")
        return None
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP Error: {e.response.status_code} {e.response.reason}")
        try:
            api_error = e.response.json().get('detail', e.response.text)
            logging.error(f"API Error Detail: {api_error}")
        except json.JSONDecodeError:
            logging.error("Could not parse error details from API response.")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while communicating with the API: {e}")
        return None


def get_ranked_moves(kata_output_json):
    """Parses the KataGo JSON and sorts all moves."""
    move_infos = kata_output_json.get('moveInfos', [])
    if not move_infos:
        logging.error("No 'moveInfos' key found in the KataGo JSON data.")
        return []
    return sorted(move_infos, key=lambda x: (x.get('playSelectionValue', 0), x.get('visits', 0)), reverse=True)


def generate_move_table(kata_output):
    """Generates a markdown table with Move, PlaySelectionValue, and Visits."""
    ranked_moves = get_ranked_moves(kata_output)
    if not ranked_moves: return "No moves to display."
    
    table = "| Rank | Move | PlaySelectionValue | Visits |\n"
    table += "|:----:|:----:|:------------------:|:------:|\n"
    for i, move in enumerate(ranked_moves[:5], 1):
        table += (f"| {i} | **{move.get('move', 'N/A')}** | {move.get('playSelectionValue', 0):<18.2f} | "
                  f"{move.get('visits', 0):<6} |\n")
    return table


def format_prompt_for_llm(kata_output):
    """Creates a simple, direct prompt to force the LLM to extract specific data."""
    ranked_moves = get_ranked_moves(kata_output)
    if not ranked_moves: return "The board is empty."
    root_info = kata_output.get("rootInfo", {})
    current_player = "Black" if root_info.get("currentPlayer") == "B" else "White"
    best_move = ranked_moves[0].get("move", "N/A")
    prompt = (f"You are a data extraction robot. Your only task is to read the provided information "
              f"and output a single sentence in a specific format.\n\n"
              f"## Data:\n- Player to move: {current_player}\n- Best Move: {best_move}\n\n"
              f"## Task:\nRespond with ONLY the following sentence, filling in the information from the data section. "
              f"Do not add any other words, explanations, or punctuation.\n\n"
              f"Sentence format: The best move for [Player to move] is [Best Move].")
    return prompt


def ask_llm(prompt, model_name):
    """Sends the prompt to the specified local LLM via Ollama."""
    import subprocess
    logging.info(f"Sending prompt to LLM model: {model_name}")
    try:
        result = subprocess.run(['ollama', 'run', model_name], input=prompt, capture_output=True, text=True,
                                timeout=LLM_TIMEOUT, check=False)
        if result.returncode != 0:
            logging.error(f"Ollama process returned an error: {result.stderr}")
            return "Error: Could not get a response from the LLM."
        return result.stdout.strip().split('\n')[0]
    except FileNotFoundError:
        logging.error("The 'ollama' command was not found. Please ensure Ollama is installed.")
        return "Error: Ollama is not installed or accessible."
    except subprocess.TimeoutExpired as e:
        logging.warning(f"LLM timed out after {LLM_TIMEOUT} seconds.")
        return e.stdout.strip().split('\n')[0] if e.stdout else "The LLM timed out."


def main():
    analysis_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file_path = os.path.join(LOGS_DIR, f'go-analysis-{analysis_id}.log')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                        handlers=[logging.FileHandler(log_file_path), logging.StreamHandler(sys.stdout)])

    parser = argparse.ArgumentParser(
        description="Analyze a specific move in a Go SGF file using a KataGo API and a specified LLM.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=("Example Usage:\n"
                "  python katanalyze.py llama3 gut --move 25 \"path/to/your game.sgf\"\n"
                "  python katanalyze.py gemma2:9b deepread --move 0 \"C:\\GoGames\\game1.sgf\""))
    parser.add_argument("llm_model", help="The name of the Ollama model to use (e.g., 'gemma2:9b', 'llama3').")
    parser.add_argument("visits_level", choices=['gut', 'read', 'deepread'],
                        help="The analysis depth:\n  gut      - 500 visits\n  read     - 1000 visits\n  deepread - 10000 visits")
    parser.add_argument("sgf_file", help="Path to the SGF file to analyze.")
    parser.add_argument("--move", type=int, required=True,
                        help="The move number to analyze. Use 0 for the initial board position. This is a required argument.")
    args = parser.parse_args()

    visits_map = {'gut': 500, 'read': 1000, 'deepread': 10000}
    katago_visits = visits_map[args.visits_level]
    move_to_analyze = args.move

    logging.info(f"Loading SGF file: {args.sgf_file}...")
    board_size, initial_stones, all_moves, initial_player = parse_sgf_file(args.sgf_file)
    if board_size is None:
        sys.exit(1)

    if move_to_analyze < 0 or move_to_analyze > len(all_moves):
        logging.error(f"Invalid move number: {move_to_analyze}. The game has {len(all_moves)} moves.")
        logging.error(f"Please provide a move number between 0 and {len(all_moves)}.")
        sys.exit(1)

    moves_up_to_target = all_moves[:move_to_analyze]

    logging.info(f"Analyzing position at move {move_to_analyze}.")
    logging.info(f"Found board size {board_size}x{board_size}, {len(initial_stones)} setup stones, and sending {len(moves_up_to_target)} moves to the engine.")
    logging.info(f"Requesting KataGo analysis via API with {katago_visits} visits (Level: {args.visits_level})...")

    kata_result = request_katago_analysis_from_api(
        board_size,
        initial_stones,
        moves_up_to_target,
        initial_player,
        katago_visits,
        move_to_analyze
    )

    if kata_result is None:
        logging.error("Exiting due to failed KataGo analysis. Check logs for details.")
        sys.exit(1)

    with open(log_file_path, 'a') as f:
        f.write("\n--- KATA GO RAW ANALYSIS (from API) ---\n")
        json.dump(kata_result, f, indent=2)
        f.write("\n\n--- MOVE ANALYSIS TABLE ---\n")
        f.write(generate_move_table(kata_result))
        f.write("--------------------------\n\n")

    prompt = format_prompt_for_llm(kata_result)
    
    with open(log_file_path, 'a') as f:
        f.write(f"--- PROMPT FOR {args.llm_model.upper()} ---\n{prompt}\n---------------------------\n\n")

    response = ask_llm(prompt, args.llm_model)
    with open(log_file_path, 'a') as f:
        f.write(f"--- RESPONSE FROM {args.llm_model.upper()} ---\n{response}\n---------------------------\n")

    print("\n" + "="*80)
    print(f"LLM ({args.llm_model}) Response for move {move_to_analyze}:")
    print(response)
    print("="*80 + "\n")
    print(f"Full analysis log saved to: {log_file_path}")


if __name__ == "__main__":
    main()
