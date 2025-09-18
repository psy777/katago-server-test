import sys
import json
import argparse
import subprocess
from sgfmill import sgf, boards

def coords_to_gtp(row, col, size):
    col_letter = chr(ord('A') + col + (1 if col >= 8 else 0))  # skip I
    row_number = size - row
    return f"{col_letter}{row_number}"

def board_to_array(board):
    size = board.side
    return [
        [
            "empty" if (s := board.get(r, c)) is None else ("black" if s == "b" else "white")
            for c in range(size)
        ]
        for r in range(size)
    ]

def sgf_to_katago_requests(sgf_path, move_indices):
    with open(sgf_path, 'rb') as f:
        game = sgf.Sgf_game.from_bytes(f.read())

    board_size = game.get_size()

    root = game.get_root()
    rules = (root.get('RU') or 'japanese').lower()

    komi_str = root.get('KM')
    komi = float(komi_str) if komi_str is not None else 6.5

    sequence = game.get_main_sequence()
    move_infos = [(i, *node.get_move()) for i, node in enumerate(sequence)]

    requests = []
    for move_num in move_indices:
        temp_board = boards.Board(board_size)
        moves = []
        for i, color, move in move_infos[:move_num+1]:
            if move:
                row, col = move
                temp_board.play(row, col, color)
                moves.append([color.upper(), coords_to_gtp(row, col, board_size)])
        player_to_move = "B" if len(moves) % 2 == 0 else "W"

        req = {
            "id": f"move_{move_num}",
            "action": "analyze",
            "rules": rules,
            "komi": komi,
            "boardXSize": board_size,
            "boardYSize": board_size,
            "board": board_to_array(temp_board),
            "moves": moves,
            "playerToMove": player_to_move,
            "includePolicy": True,
            "includeOwnership": True,
            "includePV": True,
            "maxVisits": 100
        }
        requests.append(req)
    return requests

def run_katago(requests, outfile_path=None):
    proc = subprocess.Popen(
        ["katago", "analysis", "-config", "analysis.cfg", "-model", "default_model.bin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    out_file = open(outfile_path, "w") if outfile_path else None

    for request in requests:
        json.dump(request, proc.stdin)
        proc.stdin.write("\n")
        proc.stdin.flush()

    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            if out_file:
                out_file.write(line)
            else:
                print("KataGo:", line.strip())
    except KeyboardInterrupt:
        print("Interrupted.")
    finally:
        if out_file:
            out_file.close()
        proc.stdin.close()
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("sgf_path", help="Path to .sgf file")
    parser.add_argument("--moves", nargs="+", type=int, required=True, help="List of move numbers to analyze (0-based)")
    parser.add_argument("--out", help="Output .txt file to save KataGo responses", default=None)
    args = parser.parse_args()

    requests = sgf_to_katago_requests(args.sgf_path, args.moves)
    run_katago(requests, args.out)
