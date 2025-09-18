import collections
import argparse
from sgfmill import sgf

class GoGameAnalyzer:
    """
    Analyzes a Go game from an SGF file, providing information about groups,
    liberties, and the nature of specific moves.
    """

    def __init__(self, sgf_content):
        """
        Initializes the analyzer with the content of an SGF file.

        This now includes parsing setup stones (e.g., handicap stones)
        from the SGF's root node and placing them on the board before
        the main move sequence is processed.

        Args:
            sgf_content (bytes): The raw byte content of the SGF file.
        """
        try:
            self.game = sgf.Sgf_game.from_bytes(sgf_content)
            self.board_size = self.game.get_size()
            self.board = self._initialize_board()
            self._place_setup_stones() # Correctly place handicap stones
            self.history = []
            self.ko_point = None # Simple ko check
        except ValueError as e:
            raise ValueError(f"Error parsing SGF file: {e}")

    def _initialize_board(self):
        """Creates an empty board."""
        return [['.' for _ in range(self.board_size)] for _ in range(self.board_size)]

    def _place_setup_stones(self):
        """
        Places any setup stones (e.g., handicap) from the SGF root node.
        The row coordinate is flipped to maintain consistency with the
        restored move processing logic.
        """
        root_node = self.game.get_root()
        if 'AB' in root_node.properties():
            for r, c in root_node.get('AB'):
                if 0 <= r < self.board_size and 0 <= c < self.board_size:
                    flipped_r = (self.board_size - 1) - r
                    self.board[flipped_r][c] = 'b'
        if 'AW' in root_node.properties():
            for r, c in root_node.get('AW'):
                if 0 <= r < self.board_size and 0 <= c < self.board_size:
                    flipped_r = (self.board_size - 1) - r
                    self.board[flipped_r][c] = 'w'

    def get_next_player(self):
        """
        Determines which player is to move next.
        It first checks the 'PL' property in the root node, which explicitly
        states whose turn it is. If not present, it infers from the last move.
        This is more reliable than simply counting moves.
        """
        root_node = self.game.get_root()
        # CORRECTED: First check if the 'PL' property exists to avoid a KeyError.
        if 'PL' in root_node.properties():
            pl_property = root_node.get('PL')
            return pl_property.lower()

        # If 'PL' is not present, fall back to inferring from history.
        if not self.history:
            # No moves played, and no PL property. Default to Black.
            return 'b'
        else:
            # Infer from the last move played.
            last_color = self.history[-1][1]
            return 'w' if last_color == 'b' else 'b'

    def draw_board(self, move_to_show=None):
        """
        Prints a text representation of the current board state.
        """
        if not self.board:
            print("Board is not initialized.")
            return

        col_letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        col_map = col_letters[:self.board_size]

        print(f"\n   {' '.join(col_map)}")
        for r in range(self.board_size):
            row_label = self.board_size - r
            row_cells = []
            for c in range(self.board_size):
                if move_to_show and (r, c) == move_to_show:
                    row_cells.append('S') # Mark the move being analyzed
                else:
                    stone = self.board[r][c]
                    row_cells.append(stone.replace('b', 'X').replace('w', 'O'))

            row_str = ' '.join(row_cells)
            print(f"{row_label:02d} {row_str}")
        print("")

    def _get_neighbors(self, r, c, diagonals=False):
        """Returns valid neighbors for a given coordinate."""
        deltas = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        if diagonals:
            deltas.extend([(1, 1), (1, -1), (-1, 1), (-1, -1)])

        neighbors = []
        for dr, dc in deltas:
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.board_size and 0 <= nc < self.board_size:
                neighbors.append((nr, nc))
        return neighbors

    def _find_group(self, r, c, color, visited):
        """Finds a group of stones and its liberties using BFS."""
        if (r, c) in visited or self.board[r][c] != color:
            return None, None

        group = set()
        liberties = set()
        q = collections.deque([(r, c)])
        visited.add((r, c))
        group.add((r, c))

        while q:
            curr_r, curr_c = q.popleft()
            for nr, nc in self._get_neighbors(curr_r, curr_c):
                if self.board[nr][nc] == '.':
                    liberties.add((nr, nc))
                elif self.board[nr][nc] == color and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    group.add((nr, nc))
                    q.append((nr, nc))
        return group, liberties

    def get_groups_and_liberties(self):
        """Calculates all groups on the board and their liberties."""
        visited = set()
        groups = {'black': [], 'white': []}
        for r in range(self.board_size):
            for c in range(self.board_size):
                if self.board[r][c] != '.' and (r, c) not in visited:
                    color_char = self.board[r][c]
                    color_name = 'black' if color_char == 'b' else 'white'
                    group, liberties = self._find_group(r, c, color_char, visited)
                    if group:
                        groups[color_name].append((group, len(liberties)))
        return groups

    def play_move(self, r, c, color):
        """Places a stone on the board and updates the state."""
        if not (0 <= r < self.board_size and 0 <= c < self.board_size):
            raise ValueError("Move is outside the board.")
        if self.board[r][c] != '.':
            raise ValueError(f"Intersection ({r},{c}) is already occupied.")
        if (r, c) == self.ko_point:
            raise ValueError(f"Illegal ko capture at ({r},{c}).")

        self.board[r][c] = color
        captured_stones = self._handle_captures(r, c, color)

        if len(captured_stones) == 1:
            # This is a simplification. A proper ko check requires checking
            # the full board state repetition.
            self.ko_point = captured_stones[0]
        else:
            self.ko_point = None

        self.history.append(((r, c), color))

    def _handle_captures(self, r, c, color):
        """Checks for and removes captured groups."""
        opponent_color = 'w' if color == 'b' else 'b'
        captured_stones = []
        for nr, nc in self._get_neighbors(r, c):
            if self.board[nr][nc] == opponent_color:
                group, liberties = self._find_group(nr, nc, opponent_color, set())
                if group and not liberties:
                    for gr, gc in group:
                        self.board[gr][gc] = '.'
                    captured_stones.extend(list(group))
        return captured_stones

    # --- Move Analysis Helpers ---

    def _check_pattern(self, r, c, color, patterns):
        """Generic helper to check for friendly stones at all relative positions."""
        for dr, dc in patterns:
            pr, pc = r + dr, c + dc
            # Check if the coordinate is within the board boundaries
            if not (0 <= pr < self.board_size and 0 <= pc < self.board_size):
                return False  # Part of the pattern is off-board
            # If any stone is NOT present, the pattern is not complete
            if self.board[pr][pc] != color:
                return False
        # If the loop completes without returning, all stones were found
        return True

    def _is_peep(self, r, c, color):
        """A peep is a move that threatens to cut an opponent's shape."""
        opponent_color = 'w' if color == 'b' else 'b'
        # Check for a peep at the cutting point of a one-point jump.
        if (self._check_pattern(r-1, c, opponent_color, [(0,0)]) and self._check_pattern(r+1, c, opponent_color, [(0,0)])) or \
           (self._check_pattern(r, c-1, opponent_color, [(0,0)]) and self._check_pattern(r, c+1, opponent_color, [(0,0)])):
            return True
        return False

    def _completes_bamboo_joint(self, r, c, color):
        """Checks if a move completes a Bamboo Joint (Takefu), a very strong connection."""
        # A bamboo joint is formed by two parallel one-point jumps. This move is the 4th stone.
        # Check horizontal joint to the left
        if self._check_pattern(r,c,color,[(0,-2), (1,0), (1,-2)]) or self._check_pattern(r,c,color,[(0,-2), (-1,0), (-1,-2)]): return True
        # Check horizontal joint to the right
        if self._check_pattern(r,c,color,[(0,2), (1,0), (1,2)]) or self._check_pattern(r,c,color,[(0,2), (-1,0), (-1,2)]): return True
        # Check vertical joint above
        if self._check_pattern(r,c,color,[(-2,0), (0,1), (-2,1)]) or self._check_pattern(r,c,color,[(-2,0), (0,-1), (-2,-1)]): return True
        # Check vertical joint below
        if self._check_pattern(r,c,color,[(2,0), (0,1), (2,1)]) or self._check_pattern(r,c,color,[(2,0), (0,-1), (2,-1)]): return True
        return False

    def _completes_empty_triangle(self, r, c, color):
        """Checks if a move completes an Empty Triangle, a classic "bad shape"."""
        if self._check_pattern(r, c, color, [(0, -1), (-1, 0)]): return True
        if self._check_pattern(r, c, color, [(-1, 0), (0, 1)]): return True
        if self._check_pattern(r, c, color, [(0, 1), (1, 0)]): return True
        if self._check_pattern(r, c, color, [(1, 0), (0, -1)]): return True
        return False

    def _completes_tiger_mouth(self, r, c, color):
        """Checks if a move completes a Tiger Mouth, a "good shape"."""
        if self._check_pattern(r, c, color, [(-1, -1), (1, -1)]): return True
        if self._check_pattern(r, c, color, [(-1, 1), (1, 1)]): return True
        if self._check_pattern(r, c, color, [(1, -1), (1, 1)]): return True
        if self._check_pattern(r, c, color, [(-1, -1), (-1, 1)]): return True
        return False

    def analyze_move(self, r, c, color):
        """Analyzes a given move for its properties."""
        if not (0 <= r < self.board_size and 0 <= c < self.board_size): return {"error": "Move is outside the board."}
        if self.board[r][c] != '.': return {"error": "Intersection is already occupied."}
        if (r, c) == self.ko_point: return {"error": "Illegal ko capture."}

        # --- Simulate the move on a temporary board ---
        temp_board = [row[:] for row in self.board]
        temp_board[r][c] = color
        temp_analyzer = GoGameAnalyzer.__new__(GoGameAnalyzer)
        temp_analyzer.board = temp_board
        temp_analyzer.board_size = self.board_size

        captured_stones = temp_analyzer._handle_captures(r, c, color)
        own_group, own_liberties_set = temp_analyzer._find_group(r, c, color, set())
        own_liberties = len(own_liberties_set) if own_liberties_set else 0

        # --- Basic Tactical Analysis ---
        analysis = {
            "capture": len(captured_stones) > 0,
            "connects": False, "cuts": False, "atari": False, "self_atari": False,
            "suicide": not own_liberties and not captured_stones,
            "starts_ko": False, "takes_ko": (r, c) == self.ko_point, "tenuki": False,
        }
        if analysis["suicide"]: return analysis
        analysis["self_atari"] = own_liberties == 1 and not captured_stones

        opponent_color = 'w' if color == 'b' else 'b'
        for nr, nc in self._get_neighbors(r, c):
            if temp_analyzer.board[nr][nc] == opponent_color:
                _, liberties = temp_analyzer._find_group(nr, nc, opponent_color, set())
                if liberties and len(liberties) == 1: analysis["atari"] = True

        friendly_groups, opponent_groups = set(), set()
        for nr, nc in self._get_neighbors(r,c):
            if self.board[nr][nc] == color: friendly_groups.add(frozenset(self._find_group(nr, nc, color, set())[0]))
            elif self.board[nr][nc] == opponent_color: opponent_groups.add(frozenset(self._find_group(nr, nc, opponent_color, set())[0]))

        if len(friendly_groups) > 1: analysis["connects"] = True
        if len(opponent_groups) > 1: analysis["cuts"] = True

        # --- Shape and Pattern Analysis ---
        analysis["peep"] = self._is_peep(r, c, color)
        analysis["completes_empty_triangle"] = self._completes_empty_triangle(r, c, color)
        analysis["completes_tiger_mouth"] = self._completes_tiger_mouth(r, c, color)
        analysis["completes_bamboo_joint"] = self._completes_bamboo_joint(r, c, color)
        analysis["one_point_jump"] = self._check_pattern(r, c, color, [(-2,0), (2,0), (0,-2), (0,2)]) and \
                                      not self._check_pattern(r,c, color, [(-1,0), (1,0), (0,-1), (0,1)])
        analysis["knights_move"] = self._check_pattern(r, c, color, [(1,2), (1,-2), (-1,2), (-1,-2), (2,1), (2,-1), (-2,1), (-2,-1)])
        analysis["diagonal"] = self._check_pattern(r, c, color, [(1,1), (1,-1), (-1,1), (-1,-1)])

        # --- Contextual and Strategic Analysis ---
        analysis["throw_in"] = analysis["self_atari"] and len(self._get_neighbors(r,c)) == len([n for n in self._get_neighbors(r,c) if self.board[n[0]][n[1]]==opponent_color])

        if len(captured_stones) == 1 and len(own_group) == 1 and own_liberties == 1:
             if own_liberties_set and own_liberties_set.pop() == captured_stones[0]: analysis["starts_ko"] = True

        if self.history:
            last_move, _ = self.history[-1]
            # A simple heuristic for tenuki (playing in a different area of the board)
            if (r - last_move[0])**2 + (c - last_move[1])**2 > 50: analysis["tenuki"] = True

        return analysis

    def process_sgf(self):
        """
        Processes the SGF file move by move, applying them to the board.
        The row coordinate is flipped to match the original script's logic.
        """
        for node in self.game.get_main_sequence():
            color, move = node.get_move()
            if color and move:
                row, col = move
                try:
                    # REVERTED: The row-flipping logic has been restored as requested.
                    flipped_row = (self.board_size - 1) - row
                    self.play_move(flipped_row, col, color)
                except ValueError as e:
                    print(f"Warning: Illegal move in SGF at ({row},{col}): {e}")
                    # Stop processing on illegal moves to avoid corrupting board state
                    break

def parse_move_string(move_str, board_size):
    """Parses an algebraic move string (e.g., 'd4', 'q16') into (row, col) tuple."""
    move_str = move_str.lower().strip()
    if not (2 <= len(move_str) <= 3): raise ValueError("Invalid move format.")
    col_char, row_str = move_str[0], move_str[1:]
    # Remove 'i' from the alphabet for Go coordinates
    col_letters = "abcdefghjklmnopqrstuvwxyz"
    if col_char not in col_letters[:board_size]: raise ValueError(f"Invalid column: {col_char}")
    col = col_letters.index(col_char)
    if not row_str.isdigit(): raise ValueError(f"Invalid row: {row_str}")
    # Convert from Go coordinate (e.g., 19) to 0-indexed array row
    row = board_size - int(row_str)
    if not (0 <= col < board_size and 0 <= row < board_size):
        raise ValueError(f"Move '{move_str}' is outside the board.")
    return row, col

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Analyze a Go SGF file and a potential next move.")
    parser.add_argument("sgf_file", help="Path to the SGF file.")
    parser.add_argument("--move", help="The move to analyze (e.g., 'd4', 'q16').")
    args = parser.parse_args()

    try:
        with open(args.sgf_file, "rb") as f: sgf_content = f.read()
    except FileNotFoundError: print(f"Error: SGF file not found at '{args.sgf_file}'"); exit(1)
    except Exception as e: print(f"Error reading SGF file: {e}"); exit(1)

    try:
        # Initialization now correctly sets up handicap stones
        analyzer = GoGameAnalyzer(sgf_content)
        # Move processing now uses the coordinate system from the original script
        analyzer.process_sgf()
    except ValueError as e: print(f"Error processing SGF: {e}"); exit(1)

    if args.move:
        # Determine the next player reliably
        next_player_color = analyzer.get_next_player()
        color_name = "Black" if next_player_color == 'b' else "White"

        try:
            r, c = parse_move_string(args.move, analyzer.board_size)
            print("--- Board State Before Move ---")
            analyzer.draw_board(move_to_show=(r, c))

            print(f"--- Analyzing Move for {color_name}: {args.move.upper()} (internal coords: r={r}, c={c}) ---")
            analysis = analyzer.analyze_move(r, c, next_player_color)

            if "error" in analysis:
                print(f"  Error: {analysis['error']}")
            else:
                tactics = {k:v for k,v in analysis.items() if k in ["capture", "atari", "connects", "cuts", "peep", "throw_in", "starts_ko", "takes_ko", "tenuki"] and v}
                shapes = {k:v for k,v in analysis.items() if k in ["one_point_jump", "knights_move", "diagonal"] and v}
                shape_quality = {k:v for k,v in analysis.items() if k in ["completes_empty_triangle", "completes_tiger_mouth", "completes_bamboo_joint"] and v}

                if not any([tactics, shapes, shape_quality]):
                     print("  This appears to be a simple, non-special move.")

                if tactics:
                    print("  Tactics:")
                    for key in tactics: print(f"    - Is a {key.replace('_', ' ')} move.")

                if shapes:
                    print("  Basic Shape:")
                    for key in shapes: print(f"    - Forms a {key.replace('_', ' ')}.")

                if shape_quality:
                    print("  Shape Quality:")
                    for key in shape_quality:
                        quality = "Bad Shape" if "triangle" in key else "Good Shape"
                        print(f"    - {key.replace('completes ', '').replace('_', ' ')} ({quality})")

        except ValueError as e: print(f"Error analyzing move: {e}"); exit(1)

    else:
        print("--- Final Board Summary ---")
        analyzer.draw_board()
        groups_info = analyzer.get_groups_and_liberties()
        for color, groups in groups_info.items():
            print(f"{color.capitalize()} Groups:")
            if not groups: print("  None"); continue
            for i, (group, liberties) in enumerate(sorted(groups, key=lambda x: len(x[0]), reverse=True)):
                print(f"  Group {i+1}: {len(group)} stones, {liberties} liberties")
